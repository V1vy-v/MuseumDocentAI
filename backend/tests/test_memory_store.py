# 【角色 D 负责】记忆系统与持久化单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 所有用例都在临时数据库上跑，不会碰 backend/data/chat.db。

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config            # noqa: E402
from app.services import memory, store  # noqa: E402


class TempDBTestCase(unittest.TestCase):
    """把存储层指向临时数据库的公共脚手架"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False        # 换了库，必须重新建表
        store.init_db()
        self.sid = "test-session"

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False        # 别把临时库的状态带给其他测试
        self._tmp.cleanup()

    def _seed_turns(self, turns: int, sid: str | None = None):
        sid = sid or self.sid
        for i in range(1, turns + 1):
            memory.remember(sid, "user", f"第{i}问")
            memory.remember(sid, "assistant", f"第{i}答")


class PersistenceTest(TempDBTestCase):
    """阶段一核心：服务重启后对话不丢"""

    def test_messages_survive_new_connection(self):
        memory.remember(self.sid, "user", "越王勾践剑是什么时期的文物？")
        memory.remember(self.sid, "assistant", "春秋晚期越国青铜剑。")
        store._schema_ready = False        # 强制走一次全新连接
        msgs = store.fetch_messages(self.sid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")

    def test_auto_creates_session(self):
        """前端自己生成 session_id、不调建会话接口，也必须能用"""
        self.assertFalse(store.session_exists("brand-new"))
        memory.remember("brand-new", "user", "你好")
        self.assertTrue(store.session_exists("brand-new"))

    def test_title_from_first_question_only(self):
        memory.remember(self.sid, "user", "越王勾践剑是什么时期的文物？")
        memory.remember(self.sid, "user", "再问一个别的")
        self.assertEqual(store.get_session(self.sid)["title"], "越王勾践剑是什么时期的文物？")

    def test_sources_roundtrip(self):
        memory.remember(self.sid, "assistant", "回答", sources=["示例_越王勾践剑", "展厅路线"])
        self.assertEqual(store.fetch_messages(self.sid)[0]["sources"],
                         ["示例_越王勾践剑", "展厅路线"])

    def test_resolved_stored_alongside_original(self):
        memory.remember(self.sid, "user", "它是什么年代的？",
                        resolved="越王勾践剑是什么年代的？")
        msg = store.fetch_messages(self.sid)[0]
        self.assertEqual(msg["content"], "它是什么年代的？", "用户原话必须保真")
        self.assertEqual(msg["resolved"], "越王勾践剑是什么年代的？")


class ContextWindowTest(TempDBTestCase):
    """上下文窗口：按"轮"对齐，不切断问答"""

    def test_window_length(self):
        self._seed_turns(8)
        history = memory.get_context(self.sid)["history"]
        self.assertEqual(len(history), config.RECENT_TURNS * 2)

    def test_history_starts_with_user(self):
        """旧实现按条数切窗口，会把一轮问答从中间切开，让模型看到没有提问的回答"""
        self._seed_turns(8)
        history = memory.get_context(self.sid)["history"]
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[-1]["role"], "assistant")
        self.assertEqual(history[0]["content"], "第3问")   # 8 轮 → 取最近 6 轮

    def test_short_history_returned_whole(self):
        self._seed_turns(2)
        history = memory.get_context(self.sid)["history"]
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["content"], "第1问")

    def test_empty_session_returns_empty_history(self):
        ctx = memory.get_context("never-used")
        self.assertEqual(ctx["history"], [])
        self.assertEqual(ctx["summary"], "")
        self.assertEqual(ctx["recent_sources"], [])

    def test_recall_backward_compatible(self):
        """chat.py / voice.py 依赖 recall 的返回格式，不能变"""
        self._seed_turns(3)
        recalled = memory.recall(self.sid)
        self.assertEqual(set(recalled[0].keys()), {"role", "content"})

    def test_history_items_have_no_extra_keys(self):
        """history 会原样拼进模型的 messages 数组，多带字段可能被接口拒绝"""
        self._seed_turns(2)
        history = memory.get_context(self.sid)["history"]
        for msg in history:
            self.assertEqual(set(msg.keys()), {"role", "content"})

    def test_recent_sources_signal(self):
        memory.remember(self.sid, "user", "越王勾践剑是什么？")
        memory.remember(self.sid, "assistant", "春秋晚期。", sources=["示例_越王勾践剑"])
        memory.remember(self.sid, "user", "它是什么年代的？")
        self.assertEqual(memory.get_context(self.sid)["recent_sources"], ["示例_越王勾践剑"])


class SessionGovernanceTest(TempDBTestCase):
    """会话治理：删除、级联、TTL、摘要"""

    def test_delete_cascades_messages(self):
        self._seed_turns(2)
        self.assertTrue(store.delete_session(self.sid))
        self.assertEqual(store.count_messages(self.sid), 0)

    def test_purge_expired_only_removes_old_sessions(self):
        memory.remember("old", "user", "很久以前")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
        with store._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (old_ts, "old"))
            conn.commit()
        memory.remember("fresh", "user", "刚刚")

        purged = store.purge_expired(days=7)
        self.assertEqual(purged, 1)
        self.assertFalse(store.session_exists("old"))
        self.assertTrue(store.session_exists("fresh"), "没过期的会话不能被清理")

    def test_summary_roundtrip_reaches_context(self):
        memory.remember(self.sid, "user", "问")
        store.set_summary(self.sid, "观众问了越王勾践剑的年代", 1)
        session = store.get_session(self.sid)
        self.assertEqual(session["summary"], "观众问了越王勾践剑的年代")
        self.assertEqual(session["summary_upto"], 1)
        self.assertEqual(memory.get_context(self.sid)["summary"], "观众问了越王勾践剑的年代")

    def test_list_sessions_ordered_by_recency(self):
        memory.remember("older", "user", "先问的")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        with store._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (old_ts, "older"))
            conn.commit()
        memory.remember("newer", "user", "后问的")

        ids = [s["session_id"] for s in store.list_sessions()]
        self.assertEqual(ids[0], "newer")

    def test_created_session_is_listed(self):
        sid = store.create_session()
        self.assertTrue(store.session_exists(sid))
        self.assertIn(sid, [s["session_id"] for s in store.list_sessions()])


if __name__ == "__main__":
    unittest.main(verbosity=2)
