# 【角色 D 负责】语音问答接口
#
# POST /api/voice
#   请求：multipart/form-data，字段 audio=录音文件(WAV)、session_id=会话编号
#   响应：{ question, answer, sources, audio_base64 }
#
# 处理流程（语音闭环的服务端部分，顺序与 /api/chat 保持一致）：
#   0. 旧对话累积够了就先压缩成摘要（滚动摘要，跨阈值才触发）
#   1. 录音 → mimo-v2.5-asr 听懂 → 问题文本
#   2. 取上下文 + 指代消解（语音场景尤其重要：ASR 常把"它"写成同音字"他/她"）
#   3. 用消解后的问句检索资料
#   4. 资料 + 摘要 + 历史 + 问题 → mimo 生成回答
#   5. 回答 → mimo-v2.5-tts 变成语音（base64 返回）
#   6. 问答双方记入对话历史，并记下真实 token 用量

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
        ctx = memory.get_context(session_id)                 # 2. 取上下文
        resolved, info = coreference.resolve(                #    指代消解
            question, ctx["history"], sources=ctx["recent_sources"]
        )
        query = resolved if info["changed"] else question    # 3. 检索
        sources = rag.retrieve(query)
        if not sources and query != question:
            sources = rag.retrieve(question)
        answer, usage = llm_client.chat_reply(               # 4. 生成回答
            question, ctx["history"], sources, ctx["summary"]
        )
        audio_b64 = base64.b64encode(tts_client.synthesize(answer)).decode()  # 5. 生成播报语音
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})

    # 6. 记入历史（记识别出的文字；用户消息同时保存消解结果）
    memory.remember(session_id, "user", question, resolved=resolved)
    memory.remember(session_id, "assistant", answer,
                    sources=[s["title"] for s in sources])
    memory.record_usage(session_id, usage)
    return VoiceResponse(question=question, answer=answer,
                         sources=[s["title"] for s in sources], audio_base64=audio_b64)
