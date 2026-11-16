# 【角色 D 负责】语音合成接口
#
#   POST /api/tts   {"text": "要朗读的文本"}  →  {"audio_base64": "...", "format": "wav"}
#
# 为什么单独开一个接口，而不是只依赖 /api/voice：
#   /api/voice 是"录音进 → 回答+语音出"的一整条链路，只有用录音提问时才有音频。
#   但文本问答的回答同样需要朗读（APP 里点一下喇叭、或者做成自动播报），
#   这时候再走一遍 /api/voice 就等于把识别和生成又跑一遍，纯属浪费。
#
# 这也是分段朗读的基础：文本问答先出字，再按句调这个接口合成，
# 不必等整段回答生成完才开始出声。

import base64

from fastapi import APIRouter, HTTPException

from ..schemas.chat import TtsRequest, TtsResponse
from ..services import tts_client

router = APIRouter()


@router.post("/api/tts", response_model=TtsResponse)
def synthesize(req: TtsRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400,
                            detail={"error": "empty text", "hint": "没有要朗读的内容"})

    try:
        audio = tts_client.synthesize(text)
    except tts_client.TTSUnavailable as exc:
        # 用 503 而不是 500：这是"服务暂时没有"，不是代码错了
        raise HTTPException(status_code=503,
                            detail={"error": str(exc),
                                    "hint": "语音播报暂时不可用，文字回答不受影响"})

    return TtsResponse(audio_base64=base64.b64encode(audio).decode(), format="wav")
