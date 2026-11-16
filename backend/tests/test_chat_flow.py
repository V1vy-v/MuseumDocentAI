# 【角色 D 负责】问答流程端到端测试（不联网）
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 这是本次改造最关键的回归测试：证明「先用消解后的问句检索」这个顺序修复生效。
# 改造前 /api/chat 是先检索再取历史，所以"它是什么年代的？"必然检索为空，
# 模型被指示回答"馆内资料暂未收录"——上一轮刚讲过，观众却觉得机器人失忆了。
#
# 直接调用接口函数并 mock 掉模型调用，所以不需要网络、不需要 API 密钥。

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.chat import chat                      # noqa: E402
from app.api.voice import voice                    # noqa: E402
from app.core import config                        # noqa: E402
from app.schemas.chat import ChatRequest           # noqa: E402
from app.services import llm_client, memory, rag, store, tts_client  # noqa: E402

SOURCE = {"title": "示例_越王勾践剑", "content": "春秋晚期越国青铜剑"}
EXPECTED_QUERY = "越王勾践剑是什么年代的？"
USAGE = {"prompt_tokens": 321, "completion_tokens": 40, "total_tokens": 361}


class _FakeUpload:
    """冒充 FastAPI 的 UploadFile（只需要 read()）"""

    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FlowTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False
        store.init_db()
        self.sid = "flow-session"
        # 铺一轮上文：观众问过越王勾践剑，讲解员答了并引用了资料
        memory.remember(self.sid, "user", "越王勾践剑是什么时期的文物？")
        memory.remember(self.sid, "assistant", "越王勾践剑是春秋晚期越国青铜剑。",
                        sources=["示例_越王勾践剑"])

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()


class ChatFlowTest(FlowTestCase):

    def test_retrieval_uses_resolved_question(self):
        """核心回归：检索必须拿到消解后的问句，而不是带代词的原文"""
        seen = []

        def fake_retrieve(question):
            seen.append(question)
            return [SOURCE]

        with mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("春秋晚期。", USAGE)):
            resp = chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        self.assertEqual(seen, [EXPECTED_QUERY],
                         "检索用错问句了：带代词的原文必然搜不到资料")
        self.assertEqual(resp.answer, "春秋晚期。")
        self.assertEqual(resp.sources, ["示例_越王勾践剑"])

    def test_falls_back_to_original_when_resolved_finds_nothing(self):
        """消解有猜错的可能：改写后搜不到时，退回原句再试一次"""
        seen = []

        def fake_retrieve(question):
            seen.append(question)
            return [] if question == EXPECTED_QUERY else [SOURCE]

        with mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("回答", USAGE)):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        self.assertEqual(seen, [EXPECTED_QUERY, "它是什么年代的？"])

    def test_model_gets_original_question_and_clean_history(self):
        """模型看的是观众原话；history 里不能夹带 sources / tokens 等额外字段"""
        captured = {}

        def fake_reply(question, history, sources, summary="", catalog=None):
            captured.update(question=question, history=history,
                            sources=sources, summary=summary)
            return "春秋晚期。", USAGE

        with mock.patch.object(rag, "retrieve", return_value=[SOURCE]), \
             mock.patch.object(llm_client, "chat_reply", side_effect=fake_reply):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        self.assertEqual(captured["question"], "它是什么年代的？", "模型应看到观众原话")
        self.assertEqual(captured["history"][0]["role"], "user", "历史应按轮对齐")
        for msg in captured["history"]:
            self.assertEqual(set(msg.keys()), {"role", "content"},
                             "多带字段会被模型接口拒收")
        self.assertEqual(captured["sources"], [SOURCE])

    def test_resolved_is_persisted_with_original_text(self):
        with mock.patch.object(rag, "retrieve", return_value=[SOURCE]), \
             mock.patch.object(llm_client, "chat_reply", return_value=("春秋晚期。", USAGE)):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        msgs = store.fetch_messages(self.sid)
        self.assertEqual(msgs[2]["content"], "它是什么年代的？", "原文必须保真")
        self.assertEqual(msgs[2]["resolved"], EXPECTED_QUERY, "消解结果应单独落库")
        self.assertEqual(msgs[3]["sources"], ["示例_越王勾践剑"])

    def test_second_turn_keeps_full_exhibit_conversation(self):
        """三连问的完整链路：第 3 轮"这个"也应被消解（焦点来自上一轮 sources）"""
        seen = []

        def fake_retrieve(question):
            seen.append(question)
            return [SOURCE]

        with mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("春秋晚期。", USAGE)):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        with mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("二楼青铜展厅。", USAGE)):
            chat(ChatRequest(question="这个在哪个展厅？", session_id=self.sid))

        self.assertEqual(seen, ["越王勾践剑是什么年代的？", "越王勾践剑在哪个展厅？"])

    def test_without_pronoun_retrieval_uses_original(self):
        seen = []

        def fake_retrieve(question):
            seen.append(question)
            return [SOURCE]

        with mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("回答", USAGE)):
            chat(ChatRequest(question="青铜展厅怎么走？", session_id=self.sid))

        self.assertEqual(seen, ["青铜展厅怎么走？"])


class CompactionWiringTest(FlowTestCase):
    """滚动摘要接进流程：每轮先检查压缩，并把摘要交给模型"""

    def test_maybe_compact_is_called_every_turn(self):
        with mock.patch.object(memory, "maybe_compact", return_value={"compacted": False}) as compact, \
             mock.patch.object(rag, "retrieve", return_value=[SOURCE]), \
             mock.patch.object(llm_client, "chat_reply", return_value=("回答", USAGE)):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))
        compact.assert_called_once_with(self.sid)

    def test_summary_is_passed_to_model(self):
        captured = {}

        def fake_reply(question, history, sources, summary="", catalog=None):
            captured["summary"] = summary
            return "回答", USAGE

        store.set_summary(self.sid, "更早的对话摘要", 0)
        with mock.patch.object(rag, "retrieve", return_value=[SOURCE]), \
             mock.patch.object(llm_client, "chat_reply", side_effect=fake_reply):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))

        self.assertEqual(captured["summary"], "更早的对话摘要")

    def test_usage_recorded_for_safety_valve(self):
        with mock.patch.object(rag, "retrieve", return_value=[SOURCE]), \
             mock.patch.object(llm_client, "chat_reply", return_value=("回答", USAGE)):
            chat(ChatRequest(question="它是什么年代的？", session_id=self.sid))
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"],
                         USAGE["prompt_tokens"])


class VoiceFlowTest(FlowTestCase):
    """语音链路走同一套顺序，ASR 的同音字也要能消解"""

    def test_voice_retrieval_uses_resolved_question(self):
        seen = []

        def fake_retrieve(question):
            seen.append(question)
            return [SOURCE]

        with mock.patch.object(llm_client, "transcribe", return_value="他是什么年代的？"), \
             mock.patch.object(rag, "retrieve", side_effect=fake_retrieve), \
             mock.patch.object(llm_client, "chat_reply", return_value=("春秋晚期。", USAGE)), \
             mock.patch.object(tts_client, "synthesize", return_value=b"RIFFfake"):
            resp = asyncio.run(voice(audio=_FakeUpload(b"RIFFfakewav"), session_id=self.sid))

        self.assertEqual(seen, [EXPECTED_QUERY], "ASR 出来的同音字「他」也应消解成文物名")
        self.assertEqual(resp.question, "他是什么年代的？", "返回给界面的应是识别原文")
        self.assertEqual(resp.sources, ["示例_越王勾践剑"])
        self.assertTrue(resp.audio_base64)

    def test_voice_records_usage(self):
        with mock.patch.object(llm_client, "transcribe", return_value="开放时间？"), \
             mock.patch.object(rag, "retrieve", return_value=[]), \
             mock.patch.object(llm_client, "chat_reply", return_value=("回答", USAGE)), \
             mock.patch.object(tts_client, "synthesize", return_value=b"RIFF"):
            asyncio.run(voice(audio=_FakeUpload(b"RIFF"), session_id=self.sid))
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"],
                         USAGE["prompt_tokens"])

    def test_voice_rejects_empty_audio(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(voice(audio=_FakeUpload(b""), session_id=self.sid))
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
