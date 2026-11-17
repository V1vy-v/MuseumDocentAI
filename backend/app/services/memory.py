# 【角色 D 负责】多轮对话记忆
#
# 目标：记得住上文，实现自然的连续对话（对应课题的"上下文记忆"要求）。
#
# 存储用 SQLite（见 services/store.py），服务重启后对话不再丢失。
#
# 上下文分三层，这就是"滚动摘要"的做法：
#   1. 最近一段对话 → 原文喂给模型（按 token 预算取，并按"轮"对齐）
#   2. 更早的对话   → 压缩成一段摘要（累积超过阈值时才压一次）
#   3. 全部原始消息 → 永久留在库里，接口仍能完整取回，前端照旧完整展示
# 换句话说：摘要只是数据库之上的一层"视图"，它只改变模型看到什么，
# 不删除任何数据。（这一点和常见 agent 的 compact 不同——那边原文常被替换掉。）
#
# 为什么按 token 而不是消息条数：一条 500 字的资料和一句"嗯"都算一条消息，
# 按条数切窗口完全不准。token 才是真正的资源约束。
#
# 指代消解在 services/coreference.py。

from ..core import config
from . import llm_client, store


# ======== 写入 ========

def remember(session_id: str, role: str, content: str,
             resolved: str = "", sources: list | None = None):
    """记一条对话。

    content ：用户原话 / 模型回答，保真存储（展示、摘要、日志都用它）
    resolved：指代消解后的独立问句（只有用户消息有，仅用于事后排查）
    sources ：该轮回答引用的资料标题列表
    """
    store.append_message(session_id, role, content, resolved=resolved, sources=sources)
    if role == "user":
        # 取首问当会话标题（store 内部只在标题为空时写入，不会覆盖）
        store.set_title(session_id, content[:30])


# ======== 读取 ========

def get_context(session_id: str) -> dict:
    """一次取回模型和指代消解需要的全部上文。

    返回三个键：
        summary        更早对话的压缩摘要，没有则为空串
        history        最近若干轮，[{"role","content"}]，可直接喂给模型
        recent_sources 上一轮回答引用的资料标题——指代消解最可靠的焦点信号
                       （它直接说明"上一轮到底在讲哪件文物"）
    """
    session = store.get_session(session_id)
    window = _window(session_id)
    history = [{"role": m["role"], "content": m["content"]} for m in window]
    return {
        "summary": (session or {}).get("summary", ""),
        "history": history,
        "recent_sources": _recent_sources(window),
    }


# ======== 长对话滚动摘要 ========

def maybe_compact(session_id: str) -> dict:
    """检查是否需要压缩旧对话；需要就调模型生成摘要并写回。

    触发依据是 token（config.SUMMARY_TRIGGER_TOKENS），不是消息条数。
    只处理"已滑出窗口、且尚未被摘要覆盖"的那一段，所以：
      - 大多数请求什么都不做，代价只是一次带索引的 SUM 查询
      - 跨过阈值时才多一次模型调用

    返回本次的结果，便于日志和测试观察：
        {"compacted": bool, "reason": str, ...}
    """
    session = store.get_session(session_id)
    if session is None:
        return {"compacted": False, "reason": "no_session"}

    upto = int(session.get("summary_upto") or 0)
    window = _window(session_id)
    window_start = window[0]["id"] if window else None

    pending_tokens = store.sum_tokens(session_id, after_id=upto, before_id=window_start)
    if pending_tokens < config.SUMMARY_TRIGGER_TOKENS:
        return {"compacted": False, "reason": "below_threshold",
                "pending_tokens": pending_tokens}

    pending = store.fetch_between(session_id, after_id=upto, before_id=window_start)
    if not pending:
        return {"compacted": False, "reason": "nothing_pending",
                "pending_tokens": pending_tokens}

    try:
        summary = llm_client.summarize(session.get("summary") or "", pending)
    except Exception as exc:                                    # noqa: BLE001
        # 摘要失败绝不能让正常问答挂掉——下一轮还会再触发一次
        return {"compacted": False, "reason": "summarize_failed", "error": str(exc)}

    covered_until = pending[-1]["id"]
    store.set_summary(session_id, summary, covered_until)
    return {"compacted": True, "reason": "compacted",
            "covered_until": covered_until,
            "covered_messages": len(pending),
            "pending_tokens": pending_tokens}


def record_usage(session_id: str, usage: dict) -> int:
    """记下这次请求的真实 token 用量（安全阀），返回 prompt_tokens。

    用量衡量的是**整个提示词**：人设 + 检索资料 + 摘要 + 历史 + 问题。
    如果它逼近模型上下文上限，说明光压缩历史已经不够了——多半是检索资料太大，
    这时应该告警，而不是反复做无用的压缩。
    """
    tokens = int((usage or {}).get("prompt_tokens") or 0)
    if not tokens:
        return 0
    store.set_last_prompt_tokens(session_id, tokens)
    if tokens >= config.PROMPT_TOKEN_ALERT:
        print(f"[告警] 会话 {session_id} 的提示词已达 {tokens} token，"
              f"超过警戒线 {config.PROMPT_TOKEN_ALERT}：检索资料可能过大，压缩历史已不够用")
    return tokens


# ======== 内部 ========

def _window(session_id: str) -> list:
    """按 token 预算取最近一段对话，并对齐到轮边界（以 user 开头）"""
    window = store.fetch_tail_by_tokens(session_id, config.RECENT_TOKEN_BUDGET)
    if not window:
        # 单条消息就超过整个预算（比如观众粘贴了一大段文字）。
        # 这时至少要保证带上最后一轮问答，否则模型连上一句都看不到。
        window = store.fetch_messages(session_id, limit=4)
    return _extend_to_turn_start(session_id, window)


def _extend_to_turn_start(session_id: str, window: list) -> list:
    """窗口若以 assistant 开头，往前把对应的 user 提问拉进来。

    为什么是"往前补"而不是"往后砍"：预算恰好装下奇数条消息时，
    往后砍会一次性丢掉半轮问答（极端情况下丢掉一半窗口）；
    往前补只多带一条消息，信息不丢，代价是略微超出预算。
    """
    for _ in range(3):          # 正常一问一答，补一次就够
        if not window or window[0]["role"] == "user":
            return window
        previous = store.fetch_previous(session_id, window[0]["id"])
        if previous is None:
            break               # 已经是会话第一条了
        window = [previous] + window

    # 补完仍不是 user 开头（数据异常），退化为从第一条 user 开始截取
    aligned = _from_first_user(window)
    return aligned if aligned else window


def _from_first_user(messages: list) -> list:
    """从第一条 user 消息开始截取。

    按 token 预算切出来的窗口未必落在轮的分界上，直接喂给模型会出现
    "只有回答、没有提问"的半截上下文。丢掉开头那半轮即可——
    它不会被丢弃，只是归入下批等待压缩的旧对话。
    """
    for idx, msg in enumerate(messages):
        if msg["role"] == "user":
            return messages[idx:]
    return []


def _recent_sources(messages: list) -> list:
    """最近一次带来源的回答所引用的资料标题"""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and msg.get("sources"):
            return list(msg["sources"])
    return []
