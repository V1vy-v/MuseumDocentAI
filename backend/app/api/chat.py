# 【角色 D 负责】文本问答接口
#
# POST /api/chat
#   请求：{ question: 问题文本, session_id: 会话编号 }
#   响应：{ answer: 回答文本, sources: [资料来源列表] }
#
# 处理流程：
#   1. 从 memory 取对话历史（理解"它""这个"指什么）
#   2. rag 检索博物馆资料
#   3. 资料 + 历史 + 问题 → mimo 生成回答
#   4. 双方都记入对话历史

from fastapi import APIRouter, HTTPException

from ..schemas.chat import ChatRequest, ChatResponse
from ..services import llm_client, memory, rag

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    sources = rag.retrieve(req.question)
    history = memory.recall(req.session_id)
    try:
        answer = llm_client.chat_reply(req.question, history, sources)
    except Exception as exc:  # 模型调用失败时给前端友好提示
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})
    memory.remember(req.session_id, "user", req.question)
    memory.remember(req.session_id, "assistant", answer)
    return ChatResponse(answer=answer, sources=[s["title"] for s in sources])
