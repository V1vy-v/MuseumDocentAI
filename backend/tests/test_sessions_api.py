# 【角色 D 负责】会话管理接口单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 直接调用接口函数（venv 里没有 httpx，用不了 TestClient），
# 所以不需要起服务、不需要网络。

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException                      # noqa: E402

from app.api.sessions import (create_session, delete_session, get_messages,  # noqa: E402
                              list_sessions)
from app.core import config                            # noqa: E402
from app.schemas.session import SessionCreateRequest   # noqa: E402
from app.services import memory, store                 # noqa: E402


class SessionsApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False
        store.init_db()

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()


class CreateSessionTest(SessionsApiTestCase):

    def test_create_without_body_generates_id(self):
        resp = create_session()
        self.assertTrue(resp.session_id)
        self.assertFalse(resp.existed)
        self.assertTrue(resp.created_at)
        self.assertTrue(store.session_exists(resp.session_id))

    def test_create_with_client_supplied_id(self):
        resp = create_session(SessionCreateRequest(session_id="my-own-uuid"))
        self.assertEqual(resp.session_id, "my-own-uuid")
        self.assertFalse(resp.existed, "第一次创建不该标记为已存在")
        self.assertTrue(store.session_exists("my-own-uuid"))

    def test_create_twice_reports_existed(self):
        create_session(SessionCreateRequest(session_id="dup"))
        resp = create_session(SessionCreateRequest(session_id="dup"))
        self.assertEqual(resp.session_id, "dup")
        self.assertTrue(resp.existed, "第二次应标记为已存在")

    def test_blank_id_is_treated_as_absent(self):
        """前端可能不小心传空串，不能因此建出一个空编号的会话"""
        resp = create_session(SessionCreateRequest(session_id="   "))
        self.assertTrue(resp.session_id.strip())
        self.assertNotEqual(resp.session_id.strip(), "")

    def test_two_calls_generate_different_ids(self):
        self.assertNotEqual(create_session().session_id, create_session().session_id)


class GetMessagesTest(SessionsApiTestCase):

    def test_missing_session_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            get_messages("never-existed")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_returns_history_in_order(self):
        memory.remember("s1", "user", "越王勾践剑是什么时期的文物？")
        memory.remember("s1", "assistant", "春秋晚期越国青铜剑。",
                        sources=["示例_越王勾践剑"])
        resp = get_messages("s1")
        self.assertEqual(len(resp.messages), 2)
        self.assertEqual(resp.messages[0].role, "user")
        self.assertEqual(resp.messages[1].role, "assistant")
        self.assertEqual(resp.messages[1].sources, ["示例_越王勾践剑"])

    def test_exposes_title_and_resolved_for_debugging(self):
        memory.remember("s1", "user", "越王勾践剑是什么时期的文物？")
        memory.remember("s1", "assistant", "春秋晚期。")
        memory.remember("s1", "user", "它是什么年代的？", resolved="越王勾践剑是什么年代的？")

        resp = get_messages("s1")
        self.assertEqual(resp.title, "越王勾践剑是什么时期的文物？")
        self.assertEqual(resp.messages[2].content, "它是什么年代的？", "展示用原文")
        self.assertEqual(resp.messages[2].resolved, "越王勾践剑是什么年代的？")

    def test_empty_session_returns_empty_list(self):
        sid = create_session().session_id
        resp = get_messages(sid)
        self.assertEqual(resp.messages, [])

    def test_summary_field_exposed(self):
        memory.remember("s1", "user", "问")
        store.set_summary("s1", "观众问了越王勾践剑", 1)
        self.assertEqual(get_messages("s1").summary, "观众问了越王勾践剑")


class DeleteSessionTest(SessionsApiTestCase):

    def test_delete_removes_session_and_messages(self):
        memory.remember("s1", "user", "问")
        memory.remember("s1", "assistant", "答")

        resp = delete_session("s1")
        self.assertTrue(resp.ok)
        self.assertTrue(resp.deleted)
        self.assertFalse(store.session_exists("s1"))
        self.assertEqual(store.count_messages("s1"), 0, "消息应随会话级联删除")

    def test_delete_is_idempotent(self):
        """前端本地存了过期 session_id 时，重复删除不该报错"""
        memory.remember("s1", "user", "问")
        self.assertTrue(delete_session("s1").deleted)
        again = delete_session("s1")
        self.assertTrue(again.ok)
        self.assertFalse(again.deleted)

    def test_delete_never_existing_session(self):
        resp = delete_session("never-existed")
        self.assertTrue(resp.ok)
        self.assertFalse(resp.deleted)


class RouteRegistrationTest(unittest.TestCase):
    """确认接口真的挂到了应用上（而不是写了文件忘了 include_router）。

    按"路径 + 方法"一起核对：光数路径个数会漏掉"同一路径新增了方法"这种情况
    （比如 /api/sessions 后来加了 GET 列表，路径个数是不变的）。
    """

    EXPECTED = {
        "/api/chat": {"post"},
        "/api/chat/stream": {"post"},
        "/api/voice": {"post"},
        "/api/tts": {"post"},
        "/api/health": {"get"},
        "/api/sessions": {"get", "post"},
        "/api/sessions/{session_id}/messages": {"get"},
        "/api/sessions/{session_id}": {"delete"},
        # 资料库手动检索（不经过大模型）：搜索/分页/筛选 + 原文 + 筛选项
        "/api/kb/search": {"get"},
        "/api/kb/doc": {"get"},
        "/api/kb/filters": {"get"},
    }

    def test_all_endpoints_registered_with_expected_methods(self):
        from app import main
        paths = main.app.openapi()["paths"]
        self.assertEqual(set(paths), set(self.EXPECTED))
        for path, methods in self.EXPECTED.items():
            with self.subTest(path=path):
                missing = methods - set(paths[path])
                self.assertFalse(missing, f"{path} 缺少方法 {missing}")

    def test_create_body_is_optional(self):
        """POST /api/sessions 必须允许不带请求体（前端最省事的调用方式）"""
        from app import main
        spec = main.app.openapi()["paths"]["/api/sessions"]["post"]
        self.assertFalse(spec.get("requestBody", {}).get("required", False))


class ListSessionsTest(SessionsApiTestCase):
    """GET /api/sessions：界面左侧的历史会话列表"""

    def test_empty_when_nothing_happened(self):
        resp = list_sessions()
        self.assertEqual(resp.sessions, [])
        self.assertEqual(resp.count, 0)

    def test_carries_title_and_message_count(self):
        memory.remember("s1", "user", "越王勾践剑是什么时期的文物？")
        memory.remember("s1", "assistant", "春秋晚期越国青铜剑。")
        resp = list_sessions()
        self.assertEqual(resp.count, 1)
        item = resp.sessions[0]
        self.assertEqual(item.session_id, "s1")
        self.assertEqual(item.title, "越王勾践剑是什么时期的文物？")
        self.assertEqual(item.message_count, 2)

    def test_hides_empty_sessions_by_default(self):
        create_session(SessionCreateRequest(session_id="empty"))
        memory.remember("used", "user", "问")
        ids = [s.session_id for s in list_sessions().sessions]
        self.assertNotIn("empty", ids, "没发过消息的会话不该出现在历史里")
        self.assertIn("used", ids)

    def test_include_empty_flag(self):
        create_session(SessionCreateRequest(session_id="empty"))
        ids = [s.session_id for s in list_sessions(include_empty=True).sessions]
        self.assertIn("empty", ids)

    def test_newest_first(self):
        memory.remember("older", "user", "先问的")
        old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        with store._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (old, "older"))
            conn.commit()
        memory.remember("newer", "user", "后问的")
        self.assertEqual([s.session_id for s in list_sessions().sessions][0], "newer")

    def test_respects_limit(self):
        for i in range(5):
            memory.remember(f"s{i}", "user", f"第{i}问")
        self.assertEqual(len(list_sessions(limit=2).sessions), 2)

    def test_does_not_leak_message_content(self):
        """列表只带展示需要的字段，不把消息正文一起拖出来"""
        memory.remember("s1", "user", "越王勾践剑是什么时期的文物？")
        item = list_sessions().sessions[0]
        self.assertEqual(set(item.model_dump().keys()),
                         {"session_id", "title", "created_at", "updated_at", "message_count"})


class LifespanStartupTest(unittest.TestCase):
    """服务启动流程：自动建表 + 清理过期会话

    lifespan 只在服务真正启动时执行，直接调接口函数是走不到的，
    所以这里手动进入一次 lifespan 上下文。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "fresh.db"   # 模拟全新部署：库还不存在
        store._schema_ready = False
        # 这里测的是"建表 + 清理过期会话"，不关向量索引的话 lifespan 会真的
        # 去调 embedding 接口建库 —— 单元测试不该依赖网络。
        self._orig_rag = config.RAG_VECTOR_ENABLED
        config.RAG_VECTOR_ENABLED = False

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        config.RAG_VECTOR_ENABLED = self._orig_rag
        store._schema_ready = False
        self._tmp.cleanup()

    @staticmethod
    async def _enter_lifespan():
        from app import main
        async with main.lifespan(main.app):
            pass

    def test_startup_creates_database_and_schema(self):
        self.assertFalse(config.DB_PATH.exists(), "前置条件：库尚不存在")
        asyncio.run(self._enter_lifespan())
        self.assertTrue(config.DB_PATH.exists(), "启动后应自动建库")
        # 表确实建好了：能写入并读回
        memory.remember("boot", "user", "启动后写入")
        self.assertEqual(len(store.fetch_messages("boot")), 1)

    def test_startup_purges_expired_sessions(self):
        store.init_db()
        memory.remember("stale", "user", "很久以前的会话")
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
        with store._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (old, "stale"))
            conn.commit()

        asyncio.run(self._enter_lifespan())
        self.assertFalse(store.session_exists("stale"), "过期会话应在启动时被清理")

    def test_startup_keeps_recent_sessions(self):
        store.init_db()
        memory.remember("recent", "user", "刚刚的会话")
        asyncio.run(self._enter_lifespan())
        self.assertTrue(store.session_exists("recent"), "未过期的会话不能被误删")


class DebugUiTest(unittest.TestCase):
    """调试台：纯静态单文件，不依赖任何前端工具链"""

    def test_page_file_exists_with_key_panels(self):
        from app.main import DEBUG_PAGE
        self.assertTrue(DEBUG_PAGE.exists(), f"缺少调试台页面 {DEBUG_PAGE}")
        text = DEBUG_PAGE.read_text(encoding="utf-8")
        self.assertIn("后端调试台", text)
        for panel in ("会话控制", "滚动摘要", "消息明细", "原始报文", "指代消解回归"):
            with self.subTest(panel=panel):
                self.assertIn(panel, text)

    def test_page_has_no_external_dependency(self):
        """不能引用 CDN：这台机器访问外网要走代理，离线也得能用"""
        from app.main import DEBUG_PAGE
        text = DEBUG_PAGE.read_text(encoding="utf-8")
        for bad in ("http://cdn", "https://cdn", "https://unpkg", "https://cdnjs"):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, text)

    def test_route_registered_but_hidden_from_openapi(self):
        from app import main
        paths = {getattr(r, "path", None) for r in main.app.routes}
        self.assertIn("/debug", paths, "调试台路由没挂上")
        self.assertNotIn("/debug", main.app.openapi()["paths"],
                         "调试台是工具，不该进对外接口文档")

    def test_debug_ui_parses_flat_error_shape(self):
        """调试台的错误解析要跟后端摊平后的格式一致，否则报错时显示不出提示"""
        from app.main import DEBUG_PAGE
        text = DEBUG_PAGE.read_text(encoding="utf-8")
        self.assertIn("data.hint", text)
        self.assertIn("data.error", text)


class ResponseFieldTest(SessionsApiTestCase):
    """调试台依赖的诊断字段：消解结果、每条 token、最近一次真实用量"""

    def test_messages_expose_resolved_and_tokens(self):
        memory.remember("s1", "user", "它是什么年代的？", resolved="越王勾践剑是什么年代的？")
        memory.remember("s1", "assistant", "春秋晚期越国青铜剑。")
        resp = get_messages("s1")
        self.assertEqual(resp.messages[0].resolved, "越王勾践剑是什么年代的？")
        self.assertTrue(all(m.tokens > 0 for m in resp.messages),
                        "每条消息都要带 token 估算值，否则看不出窗口是怎么切的")

    def test_exposes_last_prompt_tokens(self):
        memory.remember("s1", "user", "问")
        store.set_last_prompt_tokens("s1", 377)
        self.assertEqual(get_messages("s1").last_prompt_tokens, 377)

    def test_last_prompt_tokens_defaults_to_zero(self):
        memory.remember("s1", "user", "问")
        self.assertEqual(get_messages("s1").last_prompt_tokens, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
