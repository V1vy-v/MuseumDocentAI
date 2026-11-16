# 【角色 D 负责】语音问答接口
#
# POST /api/voice
#   请求：multipart/form-data，字段 audio=录音文件(WAV)、session_id=会话编号
#   响应：{ question, answer, sources, audio_base64 }
#
# 处理流程（语音闭环的服务端部分，顺序与 /api/chat 保持一致）：
#   0. 旧对话累积够了就先压缩成摘要（滚动摘要，跨阈值才触发）
#   1. 录音 → DeepSeek /v1/tools/asr 听懂 → 问题文本
#   2. 取上下文 + 指代消解（语音场景尤其重要：ASR 常把"它"写成同音字"他/她"）
#   3. 用消解后的问句检索资料（向量库 + BM25 混合）
#   4. 资料 + 摘要 + 历史 + 问题 → DeepSeek 生成回答
#   5. 回答 → TTS 变成语音（base64 返回）；没有 TTS 服务时 audio_base64 留空
#   6. 问答双方记入对话历史，并记下真实 token 用量
#
# 关于第 5 步：语音合成【不能】和前面的步骤放在同一个 try 里。
# 原来的写法是 TTS 一失败就整个请求 502，观众连已经生成好的文字回答都拿不到，
# 而且这一轮也不会入库——下次问"它是什么年代的"就断片了。
# 现在合成失败只是没有音频，回答照常返回、照常入库。

import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..schemas.chat import VoiceResponse
from ..services import coreference, llm_client, memory, rag, tts_client

router = APIRouter()


@router.post("/api/voice", response_model=VoiceResponse)
async def voice(audio: UploadFile = File(...), session_id: str = Form(...)):
    wav_bytes = await audio.read()
    if not wav_bytes:
        raise HTTPException(status_code=400, detail={"error": "empty audio", "hint": "没有收到录音，请重试"})

    memory.maybe_compact(session_id)                     # 0. 滚动摘要

    try:
        question = llm_client.transcribe(wav_bytes)          # 1. 听懂提问
        # ASR 没听清时返回空串（不是异常）。空问题喂给模型只会得到一段瞎猜，
        # 所以必须在这里拦住，让前端提示"再说一遍"。
        if not question.strip():
            raise HTTPException(status_code=422,
                                detail={"error": "empty transcript",
                                        "hint": "没听清，请再说一遍"})
        ctx = memory.get_context(session_id)                 # 2. 取上下文
        resolved, info = coreference.resolve(                #    指代消解
            question, ctx["history"], sources=ctx["recent_sources"]
        )
        query = resolved if info["changed"] else question    # 3. 检索
        sources = rag.retrieve(query)
        if not sources and query != question:
            sources = rag.retrieve(question)
        answer, usage = llm_client.chat_reply(               # 4. 生成回答
            question, ctx["history"], sources, ctx["summary"], rag.catalog()
        )
    except HTTPException:
        raise                                  # 上面主动抛的（如没听清）原样透传
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})

    # 5. 语音合成：失败只是没有音频，不影响回答
    try:
        audio_b64 = base64.b64encode(tts_client.synthesize(answer)).decode()
    except tts_client.TTSUnavailable as exc:
        print("[语音] TTS 不可用，只返回文字：", exc)
        audio_b64 = ""

    # 6. 记入历史（记识别出的文字；用户消息同时保存消解结果）
    memory.remember(session_id, "user", question, resolved=resolved)
    memory.remember(session_id, "assistant", answer,
                    sources=[s["title"] for s in sources])
    memory.record_usage(session_id, usage)
    return VoiceResponse(
        question=question, answer=answer,
        sources=[s["title"] for s in sources],
        audio_base64=audio_b64,
        # 检索结果就地带过来，不用像历史接口那样再按标题反查
        sources_detail=[{"title": s.get("title", ""), "heading": s.get("heading", ""),
                         "url": s.get("url", ""), "score": s.get("score", 0)}
                        for s in sources],
    )
