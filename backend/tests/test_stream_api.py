# 【角色 D 负责】流式问答（SSE）单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 不起服务、不联网：模型调用被替换成一个假的流式响应，
# SSE 事件生成器则直接消费（所以它才被抽成独立函数）。

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.chat import chat, chat_stream_events   # noqa: E402
from app.core import config                          # noqa: E402
from app.schemas.chat import ChatRequest             # noqa: E402
from app.services import llm_client, rag, store   # noqa: E402


class _FakeStream:
    """冒充 requests 的流式响应：只需要 raise_for_status() 和 iter_lines()"""

    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_lines(self):
        for line in self._lines:
            yield line if isinstance(line, bytes) else line.encode("utf-8")


def sse_lines(*chunks, done=True):
    """按真实格式造 SSE 行：data: {...} 后面跟一个空行"""
    out = []
    for chunk in chunks:
        out.append(b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8"))
        out.append(b"")
    if done:
        out.append(b"data: [DONE]")
    return out


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


def parse_events(text):
    """把 SSE 文本块解析成 [(事件名, 数据), ...]"""
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


class StreamReplyTest(unittest.TestCase):
    """llm_client.stream_reply 的解析逻辑"""

    def _collect(self, lines, status=200):
        fake = _FakeStream(lines, status)
        with mock.patch.object(llm_client.requests, "post", return_value=fake):
            return list(llm_client.stream_reply("问", [], []))

    def test_parses_deltas_and_usage(self):
        events = self._collect(sse_lines(
            delta("越王"), delta("勾践剑"),
            {"choices": [], "usage": {"prompt_tokens": 321, "total_tokens": 400}},
        ))
        self.assertEqual([p for k, p in events if k == "delta"], ["越王", "勾践剑"])
        self.assertEqual([p for k, p in events if k == "usage"],
                         [{"prompt_tokens": 321, "total_tokens": 400}])

    def test_decodes_utf8_chinese(self):
        """实测踩过的坑：iter_lines(decode_unicode=True) 会把中文解成乱码，
        必须拿原始字节自己按 UTF-8 解。这条测试守住它。"""
        events = self._collect(sse_lines(delta("越王勾践剑是春秋晚期越国青铜剑")))
        text = "".join(p for k, p in events if k == "delta")
        self.assertEqual(text, "越王勾践剑是春秋晚期越国青铜剑")
        self.assertNotIn("è", text, "出现乱码说明按 latin-1 解了")

    def test_ignores_blank_and_non_data_lines(self):
        lines = [b"", b": keep-alive", b"event: ping", b"data: " + b"{bad json",
                 b"data: " + json.dumps(delta("好")).encode(), b"", b"data: [DONE]"]
        text = "".join(p for k, p in self._collect(lines) if k == "delta")
        self.assertEqual(text, "好", "坏行和空行都不该打断整条流")

    def test_stops_at_done(self):
        lines = sse_lines(delta("前")) + [b"data: " + json.dumps(delta("后")).encode()]
        text = "".join(p for k, p in self._collect(lines) if k == "delta")
        self.assertEqual(text, "前", "[DONE] 之后的数据应被忽略")

    def test_http_error_propagates(self):
        with self.assertRaises(RuntimeError):
            self._collect([], status=401)


class ChatStreamEventsTest(unittest.TestCase):
    """SSE 事件序列与落库行为"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False
        store.init_db()
        self.sid = "stream-session"
        self.source = {"title": "示例_越王勾践剑", "content": "春秋晚期越国青铜剑"}

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()

    def _run(self, text="越王勾践剑是春秋晚期越国青铜剑。", sources=None,
             stream_side_effect=None):
        lines = sse_lines(delta(text[:6]), delta(text[6:]),
                          {"choices": [], "usage": {"prompt_tokens": 123}})
        fake = _FakeStream(lines)
        with mock.patch.object(rag, "retrieve", return_value=sources if sources is not None else [self.source]), \
             mock.patch.object(llm_client.requests, "post", return_value=fake) as post:
            if stream_side_effect is not None:
                post.side_effect = stream_side_effect
            return "".join(chat_stream_events(
                ChatRequest(question="越王勾践剑是什么时期的文物？", session_id=self.sid)))

    def test_event_order_is_meta_delta_done(self):
        events = parse_events(self._run())
        self.assertEqual([name for name, _ in events], ["meta", "delta", "delta", "done"])

    def test_meta_carries_sources_and_resolved(self):
        meta = dict(parse_events(self._run()))["meta"]
        self.assertEqual(meta["session_id"], self.sid)
        self.assertEqual(meta["sources"], ["示例_越王勾践剑"])
        self.assertEqual(meta["resolved"], "越王勾践剑是什么时期的文物？")

    def test_meta_comes_before_generation(self):
        """来源和消解结果要在模型开始生成之前就给出去，界面才能提前显示"""
        names = [name for name, _ in parse_events(self._run())]
        self.assertEqual(names[0], "meta")
        self.assertLess(names.index("meta"), names.index("delta"))

    def test_deltas_reassemble_into_answer(self):
        events = parse_events(self._run(text="越王勾践剑是春秋晚期越国青铜剑。"))
        self.assertEqual(dict(events)["done"]["answer"], "越王勾践剑是春秋晚期越国青铜剑。")

    def test_done_carries_usage(self):
        self.assertEqual(dict(parse_events(self._run()))["done"]["usage"]["prompt_tokens"], 123)

    def test_turn_is_persisted(self):
        self._run()
        msgs = store.fetch_messages(self.sid)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[1]["sources"], ["示例_越王勾践剑"])
        self.assertEqual(msgs[1]["content"], "越王勾践剑是春秋晚期越国青铜剑。")

    def test_usage_recorded(self):
        self._run()
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"], 123)


class ChatStreamErrorTest(ChatStreamEventsTest):
    """出错与中途断开——流式最容易出问题的地方"""

    def test_model_failure_becomes_error_event(self):
        """首块发出后状态码就定了，错误只能作为事件报给前端"""
        text = self._run(stream_side_effect=RuntimeError("模型挂了"))
        events = parse_events(text)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[-1][0], "error")
        self.assertIn("模型挂了", dict(events)["error"]["error"])
        self.assertTrue(dict(events)["error"]["hint"], "必须带 hint 给用户看")

    def test_retrieve_failure_also_becomes_error_event(self):
        with mock.patch.object(rag, "retrieve", side_effect=RuntimeError("检索炸了")):
            events = parse_events("".join(chat_stream_events(
                ChatRequest(question="问", session_id=self.sid))))
        self.assertEqual(events[-1][0], "error")

    def test_nothing_persisted_when_generation_fails_immediately(self):
        """模型一上来就失败，不该在历史里留下一条没有回答的提问"""
        self._run(stream_side_effect=RuntimeError("模型挂了"))
        self.assertEqual(store.fetch_messages(self.sid), [])

    def test_client_disconnect_persists_partial_answer(self):
        """客户端中途退出：已经生成的部分要落库，且不能抛 RuntimeError。

        这里守住的是"绝不能在 finally 里 yield"——
        生成器被 close() 时会抛 GeneratorExit，在 finally 里 yield 会变成
        RuntimeError: generator ignored GeneratorExit。这个测试会直接失败。
        """
        lines = sse_lines(delta("第一段"), delta("第二段"), delta("第三段"))
        fake = _FakeStream(lines)
        with mock.patch.object(rag, "retrieve", return_value=[self.source]), \
             mock.patch.object(llm_client.requests, "post", return_value=fake):
            gen = chat_stream_events(
                ChatRequest(question="越王勾践剑是什么？", session_id=self.sid))
            for chunk in gen:
                if chunk.startswith("event: delta"):
                    break
            gen.close()             # 模拟客户端断开

        msgs = store.fetch_messages(self.sid)
        self.assertEqual(len(msgs), 2, "断开时已生成的部分也该落库")
        self.assertEqual(msgs[0]["content"], "越王勾践剑是什么？")
        self.assertTrue(msgs[1]["content"])


class BackwardCompatibilityTest(ChatStreamEventsTest):
    """流式是新增接口，/api/chat 的契约必须一点没变"""

    def test_non_streaming_chat_still_works(self):
        with mock.patch.object(rag, "retrieve", return_value=[self.source]), \
             mock.patch.object(llm_client, "chat_reply",
                               return_value=("春秋晚期越国青铜剑。", {"prompt_tokens": 88})):
            resp = chat(ChatRequest(question="越王勾践剑是什么时期的文物？",
                                    session_id=self.sid))
        self.assertEqual(resp.answer, "春秋晚期越国青铜剑。")
        self.assertEqual(resp.sources, ["示例_越王勾践剑"])
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"], 88)

    def test_both_paths_share_the_same_prep(self):
        """两条路径必须共用 _prepare，否则逻辑会慢慢跑偏"""
        import inspect

        from app.api import chat as chat_module
        for func in (chat_module.chat, chat_module.chat_stream_events):
            with self.subTest(func=func.__name__):
                src = inspect.getsource(func)
                self.assertIn("_prepare(req)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
