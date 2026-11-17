# 【角色 D 负责】记忆系统、持久化与滚动摘要的单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 所有用例都在临时数据库上跑，不会碰 backend/data/chat.db。

import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config              # noqa: E402
from app.services import llm_client, memory, store  # noqa: E402


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

    def _seed_turns(self, turns: int, sid: str | None = None, tokens: int | None = None):
        """铺对话。tokens 给定时按固定 token 数写入，便于精确控制窗口"""
        sid = sid or self.sid
        for i in range(1, turns + 1):
            store.append_message(sid, "user", f"第{i}问", tokens=tokens)
            store.append_message(sid, "assistant", f"第{i}答", tokens=tokens)


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


class TokenEstimateTest(unittest.TestCase):
    """token 估算：只用于决定何时压缩，方向要偏保守（宁可高估）"""

    def test_chinese_char_counts_as_about_one_token(self):
        # 实测："你好，请只回复两个字：收到"（13 字）→ 服务端 prompt_tokens = 15
        est = store.estimate_tokens("你好，请只回复两个字：收到")
        self.assertGreaterEqual(est, 13, "不能低估")
        self.assertLessEqual(est, 25, "也不该高得离谱")

    def test_empty_text_is_zero(self):
        self.assertEqual(store.estimate_tokens(""), 0)

    def test_longer_text_costs_more(self):
        self.assertGreater(store.estimate_tokens("很长的一段话" * 10),
                           store.estimate_tokens("很短"))

    def test_tokens_persisted_on_write(self):
        """store 写入时自动估算并落库，供窗口查询使用"""
        with tempfile.TemporaryDirectory() as tmp:
            orig_db, orig_data = config.DB_PATH, config.DATA_DIR
            config.DB_PATH, config.DATA_DIR = Path(tmp) / "t.db", Path(tmp)
            store._schema_ready = False
            try:
                store.init_db()
                store.append_message("s", "user", "越王勾践剑是什么时期的文物？")
                self.assertEqual(store.fetch_messages("s")[0]["tokens"],
                                 store.estimate_tokens("越王勾践剑是什么时期的文物？"))
            finally:
                config.DB_PATH, config.DATA_DIR = orig_db, orig_data
                store._schema_ready = False


class TokenWindowTest(TempDBTestCase):
    """上下文窗口：按 token 预算取，并按"轮"对齐（以 user 开头）"""

    def test_window_never_exceeds_budget_by_more_than_one_message(self):
        self._seed_turns(8, tokens=100)          # 16 条 × 100 = 1600
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", 500):
            history = memory.get_context(self.sid)["history"]

        # 预算内是 5 条（A6,U7,A7,U8,A8 恰好 500），往前补一轮的提问后是 6 条
        self.assertEqual(len(history), 6)
        self.assertEqual(history[0]["content"], "第6问")
        self.assertEqual(history[-1]["content"], "第8答")

        # 不变式：窗口总量最多超出"一条消息"的预算，这正是"往前补"的代价上界
        window = store.fetch_messages(self.sid)[-len(history):]
        total = sum(m["tokens"] for m in window)
        self.assertLessEqual(total, 500 + max(m["tokens"] for m in window))

    def test_history_starts_with_user(self):
        """旧实现按条数切窗口，会把一轮问答从中间切开"""
        self._seed_turns(8, tokens=100)
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", 500):
            history = memory.get_context(self.sid)["history"]
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[-1]["role"], "assistant")

    def test_extends_backwards_instead_of_dropping_half_a_turn(self):
        """预算恰好装下奇数条时，应该往前补提问，而不是把回答砍掉"""
        self._seed_turns(3, tokens=100)          # 6 条 × 100 = 600
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", 300):
            history = memory.get_context(self.sid)["history"]
        # 预算内是新近 3 条 A2,U3,A3；往前补 U2 得到完整的 2 轮
        self.assertEqual([m["content"] for m in history], ["第2问", "第2答", "第3问", "第3答"])

    def test_keeps_at_least_last_turn_when_single_message_exceeds_budget(self):
        """观众粘贴一大段文字导致单条超预算时，也不能让模型看不到上一句"""
        store.append_message(self.sid, "user", "很长的问题", tokens=5000)
        store.append_message(self.sid, "assistant", "回答", tokens=5000)
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", 100):
            history = memory.get_context(self.sid)["history"]
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])

    def test_short_history_returned_whole(self):
        self._seed_turns(2, tokens=10)
        history = memory.get_context(self.sid)["history"]
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["content"], "第1问")

    def test_empty_session_returns_empty_history(self):
        ctx = memory.get_context("never-used")
        self.assertEqual(ctx["history"], [])
        self.assertEqual(ctx["summary"], "")
        self.assertEqual(ctx["recent_sources"], [])

    def test_history_items_have_no_extra_keys(self):
        """history 会原样拼进模型的 messages 数组，多带字段可能被接口拒绝"""
        self._seed_turns(2, tokens=10)
        for msg in memory.get_context(self.sid)["history"]:
            self.assertEqual(set(msg.keys()), {"role", "content"})

    def test_recent_sources_signal(self):
        memory.remember(self.sid, "user", "越王勾践剑是什么？")
        memory.remember(self.sid, "assistant", "春秋晚期。", sources=["示例_越王勾践剑"])
        memory.remember(self.sid, "user", "它是什么年代的？")
        self.assertEqual(memory.get_context(self.sid)["recent_sources"], ["示例_越王勾践剑"])


class CompactionTest(TempDBTestCase):
    """长对话滚动摘要：只在累积超过阈值时压缩一次"""

    def _compact_with(self, budget=600, threshold=500, summarize=None):
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", budget), \
             mock.patch.object(config, "SUMMARY_TRIGGER_TOKENS", threshold):
            if summarize is None:
                return memory.maybe_compact(self.sid)
            with mock.patch.object(llm_client, "summarize", **summarize):
                return memory.maybe_compact(self.sid)

    def test_below_threshold_does_nothing(self):
        self._seed_turns(3, tokens=100)          # 600 token，窗口内就装下了
        result = self._compact_with(budget=600, threshold=500)
        self.assertFalse(result["compacted"])
        self.assertEqual(result["reason"], "below_threshold")
        self.assertEqual(result["pending_tokens"], 0)

    def test_compacts_and_writes_summary(self):
        self._seed_turns(10, tokens=200)         # 20 条 × 200 = 4000
        summarize = mock.MagicMock(return_value="观众问了越王勾践剑的年代与展厅")
        result = self._compact_with(budget=600, threshold=500, summarize={"new": summarize})

        self.assertTrue(result["compacted"], result)
        self.assertEqual(result["reason"], "compacted")
        summarize.assert_called_once()
        session = store.get_session(self.sid)
        self.assertEqual(session["summary"], "观众问了越王勾践剑的年代与展厅")
        self.assertGreater(session["summary_upto"], 0)
        # 覆盖范围不能吃掉窗口内的消息
        window_ids = {m["id"] for m in store.fetch_tail_by_tokens(self.sid, 600)}
        self.assertLess(session["summary_upto"], min(window_ids))

    def test_does_not_recompact_immediately(self):
        self._seed_turns(10, tokens=200)
        self._compact_with(budget=600, threshold=500,
                           summarize={"return_value": "摘要"})
        again = self._compact_with(budget=600, threshold=500)
        self.assertFalse(again["compacted"], "刚压过的部分不该再压一次")
        self.assertEqual(again["reason"], "below_threshold")

    def test_summary_reaches_model_context(self):
        self._seed_turns(10, tokens=200)
        self._compact_with(budget=600, threshold=500,
                           summarize={"return_value": "压缩后的旧对话"})
        self.assertEqual(memory.get_context(self.sid)["summary"], "压缩后的旧对话")

    def test_merges_into_existing_summary(self):
        """第二次压缩要在旧摘要基础上合并，而不是重头总结"""
        self._seed_turns(10, tokens=200)
        store.set_summary(self.sid, "上一轮的旧摘要", 2)
        summarize = mock.MagicMock(return_value="合并后的摘要")
        self._compact_with(budget=600, threshold=500, summarize={"new": summarize})
        args, _kwargs = summarize.call_args
        self.assertEqual(args[0], "上一轮的旧摘要", "第一个参数应是已有摘要")

    def test_only_pending_messages_are_summarized(self):
        """窗口内的对话不能被重复压进摘要"""
        self._seed_turns(10, tokens=200)
        summarize = mock.MagicMock(return_value="摘要")
        with mock.patch.object(config, "RECENT_TOKEN_BUDGET", 600), \
             mock.patch.object(config, "SUMMARY_TRIGGER_TOKENS", 500), \
             mock.patch.object(llm_client, "summarize", new=summarize):
            memory.maybe_compact(self.sid)
        passed = summarize.call_args[0][1]
        window_ids = {m["id"] for m in store.fetch_tail_by_tokens(self.sid, 600)}
        self.assertFalse(window_ids & {m["id"] for m in passed},
                         "窗口内的消息不该进了摘要批次")

    def test_summarize_failure_does_not_break_anything(self):
        """摘要失败绝不能影响正常问答——下一轮会再试"""
        self._seed_turns(10, tokens=200)
        result = self._compact_with(budget=600, threshold=500,
                                    summarize={"side_effect": RuntimeError("模型挂了")})
        self.assertFalse(result["compacted"])
        self.assertEqual(result["reason"], "summarize_failed")
        self.assertEqual(store.get_session(self.sid)["summary"], "", "失败时不该写坏摘要")

    def test_missing_session_is_safe(self):
        result = memory.maybe_compact("never-existed")
        self.assertFalse(result["compacted"])
        self.assertEqual(result["reason"], "no_session")

    def test_original_messages_are_never_deleted(self):
        """摘要是"视图"，原文必须一条不少——这是和 compact 的关键区别"""
        self._seed_turns(10, tokens=200)
        before = store.count_messages(self.sid)
        self._compact_with(budget=600, threshold=500,
                           summarize={"return_value": "摘要"})
        self.assertEqual(store.count_messages(self.sid), before)
        self.assertEqual(len(store.fetch_messages(self.sid)), before)


class UsageSafetyValveTest(TempDBTestCase):
    """安全阀：记录服务端返回的真实用量，超线时告警"""

    def test_records_prompt_tokens(self):
        memory.remember(self.sid, "user", "问")
        used = memory.record_usage(self.sid, {"prompt_tokens": 1234, "total_tokens": 1300})
        self.assertEqual(used, 1234)
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"], 1234)

    def test_ignores_empty_usage(self):
        memory.remember(self.sid, "user", "问")
        self.assertEqual(memory.record_usage(self.sid, {}), 0)
        self.assertEqual(memory.record_usage(self.sid, None), 0)
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"], 0)

    def test_warns_when_prompt_exceeds_alert_line(self):
        memory.remember(self.sid, "user", "问")
        buf = io.StringIO()
        with mock.patch.object(config, "PROMPT_TOKEN_ALERT", 100), \
             contextlib.redirect_stdout(buf):
            memory.record_usage(self.sid, {"prompt_tokens": 500})
        self.assertIn("告警", buf.getvalue())
        self.assertEqual(store.get_session(self.sid)["last_prompt_tokens"], 500)

    def test_quiet_below_alert_line(self):
        memory.remember(self.sid, "user", "问")
        buf = io.StringIO()
        with mock.patch.object(config, "PROMPT_TOKEN_ALERT", 10_000), \
             contextlib.redirect_stdout(buf):
            memory.record_usage(self.sid, {"prompt_tokens": 500})
        self.assertEqual(buf.getvalue(), "")


class SessionGovernanceTest(TempDBTestCase):
    """会话治理：删除、级联、TTL、摘要"""

    def test_delete_cascades_messages(self):
        self._seed_turns(2, tokens=10)
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

    def test_empty_session_is_hidden_from_list(self):
        """建了但没发过消息的会话不该出现在历史列表里（和通用聊天应用一致）"""
        sid = store.create_session()
        self.assertTrue(store.session_exists(sid))
        self.assertNotIn(sid, [s["session_id"] for s in store.list_sessions()])

    def test_empty_session_listed_when_explicitly_requested(self):
        sid = store.create_session()
        ids = [s["session_id"] for s in store.list_sessions(include_empty=True)]
        self.assertIn(sid, ids)

    def test_list_carries_title_and_message_count(self):
        # 注意用 memory.remember 而不是 store.append_message：
        # 标题是 memory 层写进去的（取首问），直接写 store 不会设标题
        memory.remember(self.sid, "user", "越王勾践剑是什么时期的文物？")
        memory.remember(self.sid, "assistant", "春秋晚期越国青铜剑。")
        row = next(s for s in store.list_sessions() if s["session_id"] == self.sid)
        self.assertEqual(row["title"], "越王勾践剑是什么时期的文物？")
        self.assertEqual(row["message_count"], 2)

    def test_same_second_ties_are_stable(self):
        """updated_at 精度只到秒；同一秒内建的会话顺序也必须稳定，否则列表会乱跳"""
        memory.remember("a", "user", "第一个")
        memory.remember("b", "user", "第二个")
        memory.remember("c", "user", "第三个")
        for _ in range(3):
            ids = [s["session_id"] for s in store.list_sessions()]
            self.assertEqual(ids[:3], ["c", "b", "a"], "顺序应稳定，且新的在前")


class MigrationTest(unittest.TestCase):
    """老库升级：补列 + 回填 token，不需要删库重建"""

    OLD_SCHEMA = """
    CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '', summary_upto INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, resolved TEXT NOT NULL DEFAULT '',
        sources TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
    );
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "old.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(self.OLD_SCHEMA)
        conn.execute("INSERT INTO sessions (session_id, created_at, updated_at) VALUES ('s','t','t')")
        conn.execute("INSERT INTO messages (session_id, role, content, created_at) "
                     "VALUES ('s','user','越王勾践剑是什么时期的文物？','t')")
        conn.commit()
        conn.close()

        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DB_PATH, config.DATA_DIR = self.db, Path(self._tmp.name)
        store._schema_ready = False

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()

    def test_adds_missing_columns(self):
        store.init_db()
        conn = sqlite3.connect(self.db)
        msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        ses_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        conn.close()
        self.assertIn("tokens", msg_cols)
        self.assertIn("last_prompt_tokens", ses_cols)

    def test_backfills_tokens_for_existing_rows(self):
        """必须回填：全 0 会让"累计 token ≤ 预算"的窗口变成无界"""
        store.init_db()
        msg = store.fetch_messages("s")[0]
        self.assertGreater(msg["tokens"], 0)
        self.assertEqual(msg["content"], "越王勾践剑是什么时期的文物？", "老数据不能被动过")

    def test_existing_data_still_readable(self):
        store.init_db()
        self.assertTrue(store.session_exists("s"))
        self.assertEqual(len(store.fetch_messages("s")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
