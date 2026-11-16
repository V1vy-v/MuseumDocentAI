# 【角色 D 负责】语音合成 TTS 封装（当前默认不可用，见下）
#
# 把回答文本变成语音，供 APP 播报。
#
# 现状：手上没有可用的 TTS 服务。
#   火山 Ark 的 /audio/speech 和 /tts 实测都是 404；
#   DeepSeek 只提供 ASR（/v1/tools/asr），没有 TTS。
# 所以这里不再绑定某一家，而是留一个通用的 OpenAI 兼容 /audio/speech 接口：
#   在 .env 里填 TTS_API_URL / TTS_API_KEY / TTS_MODEL / TTS_VOICE 就自动启用。
#
# 没配置时的行为很重要：available() 返回 False，synthesize() 抛 TTSUnavailable。
# 调用方（api/voice.py）必须捕获它、返回文字答案 + 空音频，
# 而不是让整个请求 502 —— 否则"语音播报失败"会连"已经生成好的回答"一起丢掉。

import requests

from ..core import config


class TTSUnavailable(RuntimeError):
    """没有可用的 TTS 服务，或合成失败。调用方应降级为"只返回文字"。"""


_TIMEOUT = 60


def available() -> bool:
    return bool(config.TTS_API_URL and config.TTS_MODEL)


def synthesize(text: str) -> bytes:
    """把文字变成语音，返回音频字节。不可用时抛 TTSUnavailable。"""
    if not available():
        raise TTSUnavailable("未配置 TTS 服务（TTS_API_URL / TTS_MODEL）")

    payload = {"model": config.TTS_MODEL, "input": text}
    if config.TTS_VOICE:
        payload["voice"] = config.TTS_VOICE

    headers = {"Content-Type": "application/json"}
    if config.TTS_API_KEY:
        headers["Authorization"] = "Bearer " + config.TTS_API_KEY

    try:
        resp = requests.post(config.TTS_API_URL, headers=headers, json=payload,
                             timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TTSUnavailable(f"TTS 调用失败：{exc}") from exc

    audio = resp.content
    if not audio:
        raise TTSUnavailable("TTS 返回空音频")
    return audio
