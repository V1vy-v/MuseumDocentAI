# 【角色 D 负责】语音问答接口
#
# POST /api/voice
#   请求：multipart/form-data，字段 audio=录音文件(WAV)、session_id=会话编号
#   响应：{ answer, sources, audio_base64 }
#
# 处理流程（语音闭环的服务端部分）：
#   1. 录音 → mimo-v2.5-asr 听懂 → 问题文本
#   2. 问题 + 历史 + RAG 资料 → mimo 生成回答
#   3. 回答 → mimo-v2.5-tts 变成语音（base64 返回）
#   4. 问答双方记入对话历史

import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..schemas.chat import VoiceResponse
from ..services import llm_client, memory, rag, tts_client

router = APIRouter()


@router.post("/api/voice", response_model=VoiceResponse)
async def voice(audio: UploadFile = File(...), session_id: str = Form(...)):
    wav_bytes = await audio.read()
    if not wav_bytes:
        raise HTTPException(status_code=400, detail={"error": "empty audio", "hint": "没有收到录音，请重试"})

    try:
        question = llm_client.transcribe(wav_bytes)          # 1. 听懂提问
        sources = rag.retrieve(question)                      # 2. 检索资料
        history = memory.recall(session_id)
        answer = llm_client.chat_reply(question, history, sources)
        audio_b64 = base64.b64encode(tts_client.synthesize(answer)).decode()  # 3. 生成播报语音
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc), "hint": "AI 服务暂时不可用，请稍后再试"})

    memory.remember(session_id, "user", question)             # 4. 记入历史（记识别出的文字）
    memory.remember(session_id, "assistant", answer)
    return VoiceResponse(question=question, answer=answer,
                         sources=[s["title"] for s in sources], audio_base64=audio_b64)
