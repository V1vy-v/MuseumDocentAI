# 【角色 D 负责】句子级语音流水线测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 不起服务、不联网：TTS 被替换成假的，只验证切句、顺序、失败降级与事件序列。

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.chat import chat_stream_events      # noqa: E402
from app.core import config                      # noqa: E402
from app.schemas.chat import ChatRequest         # noqa: E402
from app.services import llm_client, rag, speech, store, tts_client   # noqa: E402


# ======== 工具 ========

class _FakeStream:
    """冒充 requests 的流式响应"""

    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self):
        for line in self._lines:
            yield line if isinstance(line, bytes) else line.encode("utf-8")


def sse_lines(*chunks):
    out = []
    for chunk in chunks:
        out.append(b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8"))
        out.append(b"")
    out.append(b"data: [DONE]")
    return out


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


def parse_events(text):
    out = []
    for block in text.strip().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if name:
            out.append((name, data))
    return out


class _TtsRecorder:
    """替身：记录每次合成的文本，可配置成失败"""

    def __init__(self, fail=False, delay=0.0):
        self.texts = []
        self.fail = fail
        self.delay = delay

    def __call__(self, text):
        self.texts.append(text)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise tts_client.TTSUnavailable("TTS 挂了")
        return b"RIFFfake"


def _drain(sp, timeout=3.0):
    """把后台线程产出的音频都收上来"""
    out = []
    end = time.time() + timeout
    while time.time() < end:
        items = sp.poll(0.1)
        if items:
            out.extend(items)
            continue
        if sp.finished():
            break
    return out


# ======== 切句 ========

class SplitSentencesTest(unittest.TestCase):
    """切句规则：句末标点才切，逗号不切，超长硬切"""

    def test_single_sentence(self):
        got, rest = speech.split_sentences("越王勾践剑是春秋晚期的越国青铜剑。")
        self.assertEqual(got, ["越王勾践剑是春秋晚期的越国青铜剑。"])
        self.assertEqual(rest, "")

    def test_multiple_sentences(self):
        got, rest = speech.split_sentences("第一句。第二句！第三句？")
        self.assertEqual(len(got), 3)
        self.assertEqual(rest, "")

    def test_comma_does_not_split(self):
        """逗号处切开会让语音一顿一顿的，必须整句保留"""
        got, _ = speech.split_sentences("它 1965 年出土，剑长 55.7 厘米，现藏于湖北省博物馆。")
        self.assertEqual(len(got), 1)

    def test_trailing_partial_stays(self):
        got, rest = speech.split_sentences("第一句。还没说完")
        self.assertEqual(got, ["第一句。"])
        self.assertEqual(rest, "还没说完")

    def test_final_flushes_rest(self):
        got, rest = speech.split_sentences("第一句。还没说完", final=True)
        self.assertEqual(len(got), 2)
        self.assertEqual(rest, "")

    def test_newline_splits(self):
        got, _ = speech.split_sentences("第一行\n第二行\n")
        self.assertEqual(len(got), 2)

    def test_long_text_without_punctuation_is_hard_split(self):
        """没有标点的长段落也要切，否则第一句永远等不到"""
        raw = "啊" * (speech._MAX_CHARS * 2 + 5)
        got, rest = speech.split_sentences(raw)
        self.assertEqual(len(got), 2)
        self.assertTrue(all(len(s) == speech._MAX_CHARS for s in got))
        self.assertEqual(len(rest), 5)


# ======== 合成流水线 ========

class SentenceSpeakerTest(unittest.TestCase):
    """后台合成：顺序、短句合并、失败降级、停止"""

    def test_audio_indices_are_ascending(self):
        rec = _TtsRecorder()
        sp = speech.SentenceSpeaker()
        with mock.patch.object(tts_client, "synthesize", rec):
            sp.start()
            sp.feed("第一句足够长的一句话。第二句也足够长的另一句话。")
            sp.flush()
            sp.close()
            items = _drain(sp)
        # poll 现在返回 (index, 句子文字, WAV字节)
        self.assertEqual([item[0] for item in items], [0, 1])
        self.assertEqual(len(rec.texts), 2)

    def test_short_fragments_are_merged(self):
        """“是。”这种两字片段不能单独合成，否则白付一次固定开销"""
        rec = _TtsRecorder()
        sp = speech.SentenceSpeaker()
        with mock.patch.object(tts_client, "synthesize", rec):
            sp.start()
            sp.feed("是。")
            sp.feed("春秋晚期越国青铜剑。")
            sp.flush()
            sp.close()
            _drain(sp)
        self.assertEqual(len(rec.texts), 1)
        self.assertIn("是。", rec.texts[0])
        self.assertIn("春秋晚期越国青铜剑。", rec.texts[0])

    def test_tts_failure_marks_error_and_stops(self):
        rec = _TtsRecorder(fail=True)
        sp = speech.SentenceSpeaker()
        with mock.patch.object(tts_client, "synthesize", rec):
            sp.start()
            sp.feed("第一句足够长的一句话。第二句也足够长的另一句话。")
            sp.flush()
            sp.close()
            items = _drain(sp)
        self.assertEqual(items, [])
        self.assertIn("TTS", sp.error)
        # 第一句失败后不再继续尝试，避免把整条流拖死
        self.assertEqual(len(rec.texts), 1)

    def test_total_chars_are_capped(self):
        """整轮有字数上限，防止模型输出超长把 TTS 额度吃光"""
        rec = _TtsRecorder()
        sp = speech.SentenceSpeaker()
        with mock.patch.object(tts_client, "synthesize", rec):
            sp.start()
            for _ in range(80):
                sp.feed("这是一句用来把字数顶到上限的测试句子。")
            sp.flush()
            sp.close()
            _drain(sp)
        self.assertLessEqual(sp.emitted_chars, speech._MAX_TOTAL)

    def test_stop_discards_remaining(self):
        """客户端断开后不该继续合成剩下的句子"""
        rec = _TtsRecorder(delay=0.05)
        sp = speech.SentenceSpeaker()
        with mock.patch.object(tts_client, "synthesize", rec):
            sp.start()
            for i in range(10):
                sp.feed("第%d句足够长的测试句子内容。" % i)
            sp.stop()
            _drain(sp, timeout=2.0)
        self.assertLess(len(rec.texts), 10)


# ======== 接口事件序列 ========

class ChatStreamAudioTest(unittest.TestCase):
    """/api/chat/stream 在 with_audio=True 时的行为"""

    TEXT = "越王勾践剑是春秋晚期的越国青铜剑。它出土于湖北江陵望山一号楚墓。"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False
        store.init_db()
        self.sid = "audio-session"
        self.source = {"title": "示例_越王勾践剑", "content": "春秋晚期越国青铜剑"}

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()

    def _run(self, with_audio=True, tts=None, available=True, text=None):
        text = text or self.TEXT
        lines = sse_lines(delta(text[:10]), delta(text[10:]))
        fake = _FakeStream(lines)
        rec = tts or _TtsRecorder()
        with mock.patch.object(rag, "retrieve", return_value=[self.source]), \
             mock.patch.object(llm_client.requests, "post", return_value=fake), \
             mock.patch.object(tts_client, "synthesize", rec), \
             mock.patch.object(tts_client, "available", return_value=available):
            body = "".join(chat_stream_events(ChatRequest(
                question="越王勾践剑是什么时期的文物？",
                session_id=self.sid, with_audio=with_audio)))
        return parse_events(body), rec

    def test_no_audio_events_by_default(self):
        """默认行为必须和以前完全一致"""
        events, rec = self._run(with_audio=False)
        names = [n for n, _ in events]
        self.assertEqual(names, ["meta", "delta", "delta", "done"])
        self.assertEqual(rec.texts, [])

    def test_audio_events_follow_done(self):
        """文字先完整（done），音频在后面继续推"""
        events, _ = self._run()
        names = [n for n, _ in events]
        self.assertEqual(names[0], "meta")
        self.assertIn("audio_done", names)
        self.assertLess(names.index("done"), names.index("audio_done"))

    def test_audio_indices_ascending(self):
        events, _ = self._run()
        idx = [d["index"] for n, d in events if n == "audio"]
        self.assertEqual(idx, sorted(idx))
        self.assertGreaterEqual(len(idx), 1)

    def test_audio_count_matches_audio_done(self):
        events, _ = self._run()
        n_audio = sum(1 for n, _ in events if n == "audio")
        done = dict(events)["audio_done"]
        self.assertEqual(done["count"], n_audio)
        self.assertEqual(done["error"], "")

    def test_audio_payload_is_playable_wav_field(self):
        events, _ = self._run()
        first = [d for n, d in events if n == "audio"][0]
        self.assertEqual(first["format"], "wav")
        self.assertTrue(first["audio_base64"])

    def test_done_still_carries_full_answer(self):
        events, _ = self._run()
        self.assertEqual(dict(events)["done"]["answer"], self.TEXT)

    def test_tts_failure_degrades_without_breaking_text(self):
        """TTS 挂了：文字、来源、done 都还在，只是没有音频"""
        events, _ = self._run(tts=_TtsRecorder(fail=True))
        names = [n for n, _ in events]
        self.assertIn("done", names)
        self.assertEqual(sum(1 for n in names if n == "audio"), 0)
        done = dict(events)["audio_done"]
        self.assertEqual(done["count"], 0)
        self.assertIn("TTS", done["error"])

    def test_missing_tts_reports_reason(self):
        events, rec = self._run(available=False)
        done = dict(events)["audio_done"]
        self.assertEqual(done["count"], 0)
        self.assertIn("TTS", done["error"])
        self.assertEqual(rec.texts, [])

    def test_turn_is_persisted(self):
        self._run()
        msgs = store.fetch_messages(self.sid)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
