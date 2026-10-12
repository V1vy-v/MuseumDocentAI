# 【角色 D 负责】对话持久化仓储层（SQLite）
#
# 分层理由：memory.py 只表达"记什么、取什么"，"存在哪、怎么存"全部收在本文件。
# 将来要换存储介质（JSONL / PostgreSQL）只改这一个文件，上层调用方不用动。
#
# 为什么选 SQLite：
#   1. 标准库自带，零新依赖；
#   2. 取"最近 N 轮"是每轮请求的热路径，需要按 session_id 建索引查询；
#   3. summary / updated_at / title 需要就地更新，而 JSONL 是只追加格式，
#      用它会被迫频繁重写整个文件；
#   4. 用户消息和助手消息的成对写入能用事务保证，不会只落一半。

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from ..core import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    summary_upto INTEGER NOT NULL DEFAULT 0,
    title        TEXT NOT NULL DEFAULT '',
    last_prompt_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    resolved    TEXT NOT NULL DEFAULT '',
    sources     TEXT NOT NULL DEFAULT '[]',
    tokens      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, id);
"""

# 增量迁移：老库缺的列在这里补上，保证升级后不用删库重建
# (表名, 列名, 列定义)
_MIGRATIONS = (
    ("sessions", "last_prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "tokens", "INTEGER NOT NULL DEFAULT 0"),
)

# 建表只做一次（进程内）。加锁是因为 FastAPI 的同步接口跑在线程池里，
# 首次并发请求会同时进来。
_schema_ready = False
_schema_lock = threading.Lock()


def _now() -> str:
    """统一用 UTC 的 ISO8601 存时间，避免服务器时区变化影响过期判断"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    """估算文本占多少 token。

    中文经验值 1 个汉字 ≈ 1 个 token（实测："你好，请只回复两个字：收到" 13 字
    → 服务端 prompt_tokens = 15，多出来的 2 个是 chat 模板的包装开销）。
    英文会低估吗？不会——英文约 4 字符/token，这里按 1 字符/token 算是**高估**，
    方向是安全的（无非早一点触发压缩）。

    这个估算只用于决定"何时压缩"；真实用量以服务端返回的 usage 为准。
    """
    if not text:
        return 0
    return len(text) + 4          # +4 约等于 role / 分隔符的固定开销


def _migrate(conn):
    """补齐老库缺失的列，让升级不必删库"""
    added = []
    for table, column, decl in _MIGRATIONS:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            added.append((table, column))

    # 刚加上 tokens 列时给老数据回填估算值。
    # 必须回填：全 0 会让"累计 token ≤ 预算"的窗口查询变成无界（0 永远不超预算）。
    if ("messages", "tokens") in added:
        conn.execute("UPDATE messages SET tokens = length(content) + 4 WHERE content <> ''")
        conn.commit()


@contextmanager
def _connect():
    """每次调用开一条连接。

    FastAPI 的同步接口运行在线程池中（多请求 = 多线程），而 sqlite3 的连接
    默认不允许跨线程复用，所以不能做成全局单例。SQLite 建连接开销极低。
    """
    global _schema_ready
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")    # 读写并发，读不被写阻塞
        conn.execute("PRAGMA busy_timeout=5000")   # 撞锁时等待，而不是立刻报错
        conn.execute("PRAGMA foreign_keys=ON")     # 让级联删除生效
        if not _schema_ready:
            with _schema_lock:
                if not _schema_ready:
                    conn.executescript(_SCHEMA)
                    _migrate(conn)
                    conn.commit()
                    _schema_ready = True
        yield conn
    finally:
        conn.close()


def init_db():
    """建表。首次访问任一函数时会自动建，这里提供显式入口供服务启动时调用。"""
    with _connect():
        pass


# ======== 会话 ========

def ensure_session(session_id: str) -> bool:
    """确保会话存在，返回"本次是否新建"。

    前端目前是自己生成 UUID 的，不会先调建会话接口，所以任何写入前都要兜底建会话。
    """
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        conn.commit()
        return cur.rowcount > 0


def create_session(session_id: str | None = None) -> str:
    """新建会话并返回编号（不传则自动生成）"""
    sid = session_id or str(uuid.uuid4())
    ensure_session(sid)
    return sid


def session_exists(session_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row is not None


def get_session(session_id: str) -> dict | None:
    """取会话元信息（含 summary / summary_upto / title），不存在返回 None"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def list_sessions(limit: int = 50, include_empty: bool = False) -> list:
    """按最近活跃倒序列出会话（历史会话列表用）。

    默认**不返回空会话**（建了但一条消息都没发过的）——和通用聊天应用的行为一致：
    新建对话在发出第一条消息之前，不该出现在历史列表里。

    updated_at 精度只到秒，同一秒内建的会话会并列，所以再用 rowid 兜一层，
    保证顺序稳定（否则列表每次刷新都可能换位置）。
    """
    sql = (
        "SELECT s.session_id, s.title, s.created_at, s.updated_at, "
        "       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS message_count "
        "FROM sessions s "
    )
    if not include_empty:
        sql += "WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id) "
    sql += "ORDER BY s.updated_at DESC, s.rowid DESC LIMIT ?"

    with _connect() as conn:
        rows = conn.execute(sql, (max(int(limit), 1),)).fetchall()
        return [dict(r) for r in rows]


def set_title(session_id: str, title: str):
    """给会话打标题（一般取首问）。只在还没有标题时写入，不覆盖。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET title = ? WHERE session_id = ? AND title = ''",
            (title, session_id),
        )
        conn.commit()


def set_summary(session_id: str, summary: str, upto: int):
    """保存滚动摘要：summary 是压缩后的文本，upto 是已覆盖到的 messages.id"""
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET summary = ?, summary_upto = ?, updated_at = ? WHERE session_id = ?",
            (summary, upto, _now(), session_id),
        )
        conn.commit()


def delete_session(session_id: str) -> bool:
    """删除会话及其全部消息（靠外键级联），返回是否删掉了东西"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0


def purge_expired(days: int | None = None) -> int:
    """清理超过 TTL 没活动的会话，返回删除的会话数（消息随外键级联删除）"""
    days = config.SESSION_TTL_DAYS if days is None else days
    deadline = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE updated_at < ?", (deadline,))
        conn.commit()
        return cur.rowcount


# ======== 消息 ========

def append_message(session_id: str, role: str, content: str,
                   resolved: str = "", sources: list | None = None,
                   tokens: int | None = None) -> int:
    """追加一条消息，返回它的自增 id。

    content ：用户原话 / 模型回答，保真存储（展示、摘要、日志都用它）
    resolved：指代消解后的独立问句，仅用于检索，不影响展示
    sources ：该轮回答引用的资料标题列表，落库供历史回放排查
    tokens  ：这条消息占多少 token（不传则按 content 估算），窗口和压缩都靠它

    三条语句在同一个事务里提交，避免会话建了但消息没落、或者消息落了时间没更新。
    """
    now = _now()
    payload = json.dumps(sources or [], ensure_ascii=False)
    if tokens is None:
        tokens = estimate_tokens(content)
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, resolved, sources, tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, resolved, payload, tokens, now),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
        conn.commit()
        return int(cur.lastrowid)


def fetch_messages(session_id: str, limit: int | None = None) -> list:
    """按时间正序取出会话消息。

    limit 给定时取"最近 limit 条"（内部倒序取再翻回正序），用于给模型喂上文；
    不传则返回全部（前端恢复历史用）。
    """
    with _connect() as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
    return [_to_message(r) for r in rows]


def count_messages(session_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])


def fetch_tail_by_tokens(session_id: str, token_budget: int) -> list:
    """从最新一条往回取，直到累计 token 不超过预算；返回正序列表。

    用 SQL 窗口函数在库里累加，避免为了找窗口边界把整个会话读进内存。
    注意这是"尽量装满预算"，不保证正好卡在预算上——边界未必落在轮的分界，
    按轮对齐由 memory 层负责。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ("
            "  SELECT *, SUM(tokens) OVER (ORDER BY id DESC "
            "      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS _cum "
            "  FROM messages WHERE session_id = ?"
            ") WHERE _cum <= ? ORDER BY id",
            (session_id, max(int(token_budget), 0)),
        ).fetchall()
    return [_to_message(r) for r in rows]


def fetch_between(session_id: str, after_id: int = 0, before_id: int | None = None) -> list:
    """取 id 落在 (after_id, before_id) 区间内的消息，正序。

    用来挑出"已滑出窗口、且还没被摘要覆盖"的那批，交给摘要压缩。
    before_id 传 None 表示不限上界。
    """
    sql = "SELECT * FROM messages WHERE session_id = ? AND id > ?"
    params = [session_id, after_id]
    if before_id:
        sql += " AND id < ?"
        params.append(before_id)
    sql += " ORDER BY id"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_to_message(r) for r in rows]


def fetch_previous(session_id: str, before_id: int) -> dict | None:
    """取紧邻 before_id 之前的那一条消息（窗口往前补一轮时用）"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (session_id, before_id),
        ).fetchone()
    return _to_message(row) if row else None


def sum_tokens(session_id: str, after_id: int = 0, before_id: int | None = None) -> int:
    """统计某区间消息的 token 总和（决定要不要压缩）"""
    sql = "SELECT COALESCE(SUM(tokens), 0) AS n FROM messages WHERE session_id = ? AND id > ?"
    params = [session_id, after_id]
    if before_id:
        sql += " AND id < ?"
        params.append(before_id)
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return int(row["n"])


def set_last_prompt_tokens(session_id: str, tokens: int):
    """记下最近一次请求的真实 prompt token 数（来自服务端 usage）"""
    with _connect() as conn:
        conn.execute("UPDATE sessions SET last_prompt_tokens = ? WHERE session_id = ?",
                     (int(tokens), session_id))
        conn.commit()


def _to_message(row: sqlite3.Row) -> dict:
    """数据库行 → 字典（sources 从 JSON 字符串还原成列表）"""
    try:
        sources = json.loads(row["sources"])
    except (ValueError, TypeError):
        sources = []
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "resolved": row["resolved"],
        "sources": sources,
        "tokens": row["tokens"],
        "created_at": row["created_at"],
    }
