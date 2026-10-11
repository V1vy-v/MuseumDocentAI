# 【角色 D 负责】多轮对话记忆
#
# 目标：记得住上文，实现自然的连续对话（对应课题的"上下文记忆"要求）。
#
# 存储已从"进程内字典"换成 SQLite（见 services/store.py），服务重启后对话不再丢失。
# 对外接口（remember / recall）保持原样，所以 api/chat.py、api/voice.py 不用改。
#
# 相关模块：
#   指代消解 → services/coreference.py（阶段二）
#   长对话摘要 → 阶段四

from ..core import config
from . import store


def remember(session_id: str, role: str, content: str,
             resolved: str = "", sources: list | None = None):
    """记一条对话。

    content ：用户原话 / 模型回答，保真存储
    resolved：指代消解后的独立问句（只有用户消息有，仅用于事后排查）
    sources ：该轮回答引用的资料标题列表
    """
    store.append_message(session_id, role, content, resolved=resolved, sources=sources)
    if role == "user":
        # 取首问当会话标题（store 内部只在标题为空时写入，不会覆盖）
        store.set_title(session_id, content[:30])


def recall(session_id: str) -> list:
    """取该会话的对话历史（给模型看的上文），返回 [{"role","content"}]"""
    messages = store.fetch_messages(session_id, limit=_fetch_limit())
    return [{"role": m["role"], "content": m["content"]} for m in _align_turns(messages)]


def get_context(session_id: str) -> dict:
    """一次取回模型和指代消解需要的全部上文。

    返回三个键：
        summary        历史摘要（阶段四接入后非空）
        history        最近若干轮，[{"role","content"}]，可直接喂给模型
        recent_sources 上一轮回答引用的资料标题——指代消解最可靠的焦点信号
                       （它直接说明"上一轮到底在讲哪件文物"）

    history 按"轮"对齐，保证以 user 消息开头，
    不会出现"只有回答、没有对应提问"的半截上下文。
    """
    session = store.get_session(session_id)
    messages = store.fetch_messages(session_id, limit=_fetch_limit())
    aligned = _align_turns(messages)
    history = [{"role": m["role"], "content": m["content"]} for m in aligned]
    return {
        "summary": (session or {}).get("summary", ""),
        "history": history,
        "recent_sources": _recent_sources(aligned),
    }


def _recent_sources(messages: list) -> list:
    """最近一次带来源的回答所引用的资料标题"""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and msg.get("sources"):
            return list(msg["sources"])
    return []


def _fetch_limit() -> int:
    """多取几条做缓冲：滑动窗口切下去的位置不一定是 user 消息"""
    return config.RECENT_TURNS * 2 + 4


def _align_turns(messages: list) -> list:
    """从尾部截取最近 RECENT_TURNS 轮，并保证结果以 user 消息开头。

    旧的实现按"条数"切窗口，会把一轮问答从中间切断（history 以 assistant 开头），
    模型于是看到一个没有提问的回答。这里改成从尾部数 user 消息定位切点。
    """
    if not messages or config.RECENT_TURNS <= 0:
        return []
    remaining = config.RECENT_TURNS
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx]["role"] == "user":
            remaining -= 1
            if remaining <= 0:
                return messages[idx:]
    return messages
