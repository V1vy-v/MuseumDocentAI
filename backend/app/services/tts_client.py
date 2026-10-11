# 【角色 D 负责】语音合成 TTS 封装
#
# 把回答文本变成语音，供 APP 播报。
# 用的是同一个平台的 mimo-v2.5-tts（已实测可用，不需要另外找 TTS API）。
# 实测格式：messages 里放 assistant 角色的文本，回复的
#           choices[0].message.audio.data 是 base64 编码的 WAV 音频。

import base64

import requests

from ..core import config

_TIMEOUT = 60


def synthesize(text: str) -> bytes:
    """把文字变成语音，返回 WAV 音频字节"""
    resp = requests.post(
        config.MIMO_API_URL + "/chat/completions",
        headers={"Authorization": "Bearer " + config.MIMO_API_KEY, "Content-Type": "application/json"},
        json={"model": config.MIMO_TTS_MODEL, "messages": [{"role": "assistant", "content": text}]},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    audio_b64 = resp.json()["choices"][0]["message"]["audio"]["data"]
    return base64.b64decode(audio_b64)
