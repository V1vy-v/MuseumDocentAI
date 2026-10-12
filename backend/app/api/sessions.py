# 【角色 D 负责】会话管理接口
#
#   POST   /api/sessions                        新建会话（编号可自带）
#   GET    /api/sessions/{session_id}/messages  拉取历史（APP 重启后回填界面）
#   DELETE /api/sessions/{session_id}           清除会话
#
# 为什么是"可选的增强"而不是必需：
#   /api/chat 和 /api/voice 在首次写入时会自动建会话（store 里做了兜底），
#   所以前端照旧自己生成 UUID、完全不调这三个接口，问答和持久化也照样工作。
#   只有想实现"重启 APP 后恢复上次对话"才需要用到它们。
#
# 这样前端可以先不动，后端先上线，两边解耦。

from fastapi import APIRouter, HTTPException

from ..schemas.session import (MessageItem, SessionCreateRequest, SessionCreateResponse,
                               SessionDeleteResponse, SessionListResponse,
                               SessionMessagesResponse, SessionSummary)
from ..services import store

router = APIRouter()


@router.get("/api/sessions", response_model=SessionListResponse)
def list_sessions(limit: int = 50, include_empty: bool = False):
    """列出历史会话（按最近活跃倒序），供界面左侧的会话列表使用。

    默认不返回空会话——新建对话在发出第一条消息之前不该出现在历史里，
    这和通用聊天应用的行为一致。要连空会话一起看就传 include_empty=true。
    """
    sessions = store.list_sessions(limit=limit, include_empty=include_empty)
    return SessionListResponse(
        sessions=[SessionSummary(**s) for s in sessions],
        count=len(sessions),
    )


@router.post("/api/sessions", response_model=SessionCreateResponse)
def create_session(req: SessionCreateRequest | None = None):
    """新建会话。请求体可省略，也可带 session_id 沿用前端自己生成的编号。"""
    wanted = (req.session_id or "").strip() if req else ""

    if wanted:
        existed = store.session_exists(wanted)
        store.ensure_session(wanted)
        session_id = wanted
    else:
        existed = False
        session_id = store.create_session()

    session = store.get_session(session_id) or {}
    return SessionCreateResponse(session_id=session_id,
                                 created_at=session.get("created_at", ""),
                                 existed=existed)


@router.get("/api/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def get_messages(session_id: str):
    """拉取某会话的全部历史消息（按时间正序），供 APP 重启后回填对话界面"""
    session = store.get_session(session_id)
    if session is None:
        # 会话可能从没建过，或者已被 TTL 清理掉
        raise HTTPException(status_code=404,
                            detail={"error": "session not found",
                                    "hint": "该会话不存在或已被清理"})

    messages = store.fetch_messages(session_id)
    return SessionMessagesResponse(
        session_id=session_id,
        title=session.get("title", ""),
        summary=session.get("summary", ""),
        created_at=session.get("created_at", ""),
        updated_at=session.get("updated_at", ""),
        last_prompt_tokens=session.get("last_prompt_tokens", 0),
        messages=[MessageItem(role=m["role"], content=m["content"], sources=m["sources"],
                              created_at=m["created_at"], resolved=m["resolved"],
                              tokens=m["tokens"])
                  for m in messages],
    )


@router.delete("/api/sessions/{session_id}", response_model=SessionDeleteResponse)
def delete_session(session_id: str):
    """清除会话及其全部消息。

    删除做成幂等：会话不存在时返回 deleted=false 而不是报错。
    前端本地存了过期的 session_id 时（比如服务端已按 TTL 清理），
    直接当成删除成功处理更省事，不必让用户看到报错。
    """
    return SessionDeleteResponse(ok=True, deleted=store.delete_session(session_id))
