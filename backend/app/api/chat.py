# 【角色 D 负责】文本问答接口
#
# POST /api/chat         非流式：{ question, session_id } → { answer, sources }
# POST /api/chat/stream  流式（SSE）：事件 meta → delta* → done（或 error）
#
# 处理流程（顺序很关键，两个接口共用同一份）：
#   0. 旧对话累积够了就先压缩成摘要（跨阈值时才真的调模型，多数请求什么都不做）
#   1. 从 memory 取上下文（摘要 + 最近若干轮 + 上一轮引用的资料）
#   2. coreference 做指代消解："它是什么年代的" → "越王勾践剑是什么年代的"
#   3. rag 用【消解后的问句】检索——用原句检索只会切出一堆虚词片，必然搜不到
#   4. 资料 + 摘要 + 历史 + 问题 → DeepSeek 生成回答
#   5. 双方都记入对话历史（用户消息同时记录原文和消解结果），并记下真实 token 用量
#
# 为什么流式做成【新增接口】而不是改 /api/chat：
#   /api/chat 是和安卓前端的冻结契约。直接改会打断角色 A 的工作，而且答辩前
#   万一流式那条路出问题就没了退路。新增一条路径，前端接不接、什么时候接都行，
#   旧版本 APP 永远能用。

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..schemas.chat import ChatRequest, ChatResponse
from ..services import coreference, llm_client, memory, rag

router = APIRouter()


def _prepare(req: ChatRequest) -> tuple:
    """生成之前的公共步骤：压缩 → 取上下文 → 指代消解 → 检索。

    返回 (ctx, resolved, sources, titles)。两个接口共用，避免逻辑跑偏。
    """
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
    #    retrieval 字段让调试台可以强制指定"关键词/向量"，用于演示时的 A/B 对比。
    query = resolved if info["changed"] else req.question
    sources = rag.retrieve(query, mode=req.retrieval)
    if not sources and query != req.question:
        sources = rag.retrieve(req.question, mode=req.retrieval)

    return ctx, resolved, sources, [s["title"] for s in sources], rag.catalog()


def _save(session_id: str, question: str, answer: str, resolved: str, titles: list):
    """把一轮问答落库。

    没有答案就不写：模型一上来就失败时，不该在历史里留下一条没有回答的提问
    （那会让上下文窗口按"轮"对齐时出现两个连续的 user 消息）。
    """
    if not answer:
        return
    memory.remember(session_id, "user", question, resolved=resolved)
    memory.remember(session_id, "assistant", answer, sources=titles)


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    ctx, resolved, sources, titles, catalog = _prepare(req)

    # 4. 生成回答（模型看到的是观众原话，不是消解后的改写）
    try:
        answer, usage = llm_client.chat_reply(
            req.question, ctx["history"], sources, ctx["summary"], catalog
        )
    except Exception as exc:  # 模型调用失败时给前端友好提示
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})

    # 5. 记入历史：content 存原话（保真），resolved 单存一列供事后排查
    _save(req.session_id, req.question, answer, resolved, titles)
    memory.record_usage(req.session_id, usage)          # 安全阀：记下真实用量

    return ChatResponse(answer=answer, sources=titles)


# ======== 流式（SSE）========

def _sse(name: str, payload: dict) -> str:
    """拼一个 SSE 事件。末尾那个空行是事件分隔符，不能省。"""
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def chat_stream_events(req: ChatRequest):
    """SSE 事件生成器。

    抽成独立函数（而不是藏在路由里）是为了能直接单测——不必起服务，
    直接消费这个生成器就能验证事件序列、出错行为、以及"中途断开"的处理。

    事件：
        meta  {session_id, sources, resolved}  先给来源与消解结果，界面可提前显示
        delta {text}                           文本增量
        done  {answer, usage}                  正常结束
        error {error, hint}                    中途出错（响应头已发出，改不了状态码）
    """
    buf = []
    usage = {}
    resolved = req.question      # 必须在 try 之前初始化：finally 里要用
    titles = []
    try:
        ctx, resolved, sources, titles, catalog = _prepare(req)
        yield _sse("meta", {"session_id": req.session_id,
                            "sources": titles,
                            # sources_detail 只在这个流式接口里给：带原文链接和小节，
                            # debug 界面拿它渲染可点的来源气泡。
                            # /api/chat 的响应形状不动（那是和安卓端的冻结契约）。
                            "sources_detail": [
                                {"title": s.get("title", ""),
                                 "heading": s.get("heading", ""),
                                 "url": s.get("url", ""),
                                 "score": s.get("score", 0)}
                                for s in sources
                            ],
                            "resolved": resolved})

        for kind, payload in llm_client.stream_reply(
                req.question, ctx["history"], sources, ctx["summary"], catalog):
            if kind == "delta":
                buf.append(payload)
                yield _sse("delta", {"text": payload})
            else:
                usage = payload

        yield _sse("done", {"answer": "".join(buf), "usage": usage})
    except Exception as exc:                                     # noqa: BLE001
        # 首块一旦发出，状态码就定了，错误只能作为事件报给前端
        yield _sse("error", {"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})
    finally:
        # 客户端中途断开时，这里会被抛 GeneratorExit——所以【绝对不能 yield】。
        # 在 finally 里 yield 会触发 RuntimeError: generator ignored GeneratorExit。
        # 但落库必须做：否则中途退出的一轮就丢了，下一轮问"它是什么"会断片。
        _save(req.session_id, req.question, "".join(buf), resolved, titles)
        memory.record_usage(req.session_id, usage)


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """流式问答（SSE）。

    实测收益（2026-10）：首字 1.85~3.03s，而整段要 24~30s——
    感知延迟降约 10 倍，总时长不变。
    """
    return StreamingResponse(
        chat_stream_events(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",      # 别让 nginx 类代理把流缓冲起来
        },
    )
