# 【角色 D 负责】文本问答接口
#
# POST /api/chat
#   请求：{ question: 问题文本, session_id: 会话编号 }
#   响应：{ answer: 回答文本, sources: [资料来源列表] }
#
# 处理流程（顺序很关键）：
#   0. 旧对话累积够了就先压缩成摘要（跨阈值时才真的调模型，多数请求什么都不做）
#   1. 从 memory 取上下文（摘要 + 最近若干轮 + 上一轮引用的资料）
#   2. coreference 做指代消解："它是什么年代的" → "越王勾践剑是什么年代的"
#   3. rag 用【消解后的问句】检索——用原句检索只会切出一堆虚词片，必然搜不到
#   4. 资料 + 摘要 + 历史 + 问题 → mimo 生成回答
#   5. 双方都记入对话历史（用户消息同时记录原文和消解结果），并记下真实 token 用量

from fastapi import APIRouter, HTTPException

from ..schemas.chat import ChatRequest, ChatResponse
from ..services import coreference, llm_client, memory, rag

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # 0. 长对话滚动摘要：只有累积超过阈值时才真的压缩
    memory.maybe_compact(req.session_id)

    # 1. 取上下文（若上一步压缩过，这里拿到的就是新摘要）
    ctx = memory.get_context(req.session_id)

    # 2. 指代消解
    resolved, info = coreference.resolve(
        req.question, ctx["history"], sources=ctx["recent_sources"]
    )

    # 3. 检索。消解有猜错的可能，所以先用改写后的问句检索，
    #    没命中再退回原句兜一次（两路都试，成本只是多一次本地关键词匹配）
    query = resolved if info["changed"] else req.question
    sources = rag.retrieve(query)
    if not sources and query != req.question:
        sources = rag.retrieve(req.question)

    # 4. 生成回答（模型看到的是观众原话，不是消解后的改写）
    try:
        answer, usage = llm_client.chat_reply(
            req.question, ctx["history"], sources, ctx["summary"]
        )
    except Exception as exc:  # 模型调用失败时给前端友好提示
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})

    # 5. 记入历史：content 存原话（保真），resolved 单存一列供事后排查
    memory.remember(req.session_id, "user", req.question, resolved=resolved)
    memory.remember(req.session_id, "assistant", answer,
                    sources=[s["title"] for s in sources])
    memory.record_usage(req.session_id, usage)          # 安全阀：记下真实用量

    return ChatResponse(answer=answer, sources=[s["title"] for s in sources])
