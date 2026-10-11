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

from app.api.sessions import create_session, delete_session, get_messages  # noqa: E402
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
    """确认新接口真的挂到了应用上（而不是写了文件忘了 include_router）"""

    def test_all_six_endpoints_registered(self):
        from app import main
        paths = main.app.openapi()["paths"]
        for path in ("/api/chat", "/api/voice", "/api/health",
                     "/api/sessions", "/api/sessions/{session_id}/messages",
                     "/api/sessions/{session_id}"):
            with self.subTest(path=path):
                self.assertIn(path, paths)
        self.assertEqual(len(paths), 6, f"接口数应为 6，实际 {sorted(paths)}")

    def test_create_body_is_optional(self):
        """POST /api/sessions 必须允许不带请求体（前端最省事的调用方式）"""
        from app import main
        spec = main.app.openapi()["paths"]["/api/sessions"]["post"]
        self.assertFalse(spec.get("requestBody", {}).get("required", False))


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

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
