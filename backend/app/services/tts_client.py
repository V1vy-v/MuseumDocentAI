# 【角色 D 负责】语音合成 TTS 封装
#
# 把回答文本变成语音，供 APP 播报。
#
# 主用 DeepSeek 的工具接口（实测可用）：
#   POST https://api.deepseek.com/v1/tools/tts
#   {"text": "要朗读的文本"}
#   → 200, Content-Type: audio/wav, 响应体是 PCM 16bit 单声道 24kHz 的 WAV
#   （字段名是 text；传 input 会 400 "missing field `text`"）
# 实测耗时：3 个字 1.5s，78 个字 3.2s —— 大头是固定开销，之后约 20ms/字。
#
# 两个必须处理的坑：
#   1. 返回的是【流式 WAV】：RIFF 头里总长度和 data 块长度都写着 0xFFFFFFFF
#      （生成时还不知道最终多长）。标准库 wave 能打开，但会把时长算成
#      89478 秒；Android 播放器同理，进度条会显示成天文数字。
#      所以返回给客户端之前要把这两处长度补成真实值（见 _fix_wav_sizes）。
#   2. 合成失败不能连累回答：调用方（api/voice.py）捕获 TTSUnavailable，
#      降级成"只返回文字、audio_base64 留空"，而不是整个请求 502。

import struct

import requests

from ..core import config


class TTSUnavailable(RuntimeError):
    """没有可用的 TTS 服务，或合成失败。调用方应降级为"只返回文字"。"""


_TIMEOUT = 120          # 长文本合成慢，给足时间（实测 78 字约 3 秒）


def available() -> bool:
    """有 DeepSeek key 或配了通用 TTS 服务就能用"""
    return bool(config.DEEPSEEK_API_KEY or (config.TTS_API_URL and config.TTS_MODEL))


def _fix_wav_sizes(data: bytes) -> bytes:
    """把流式 WAV 里的 0xFFFFFFFF 长度字段改成真实值。

    RIFF 结构：偏移 4~8 是整块长度，每个 chunk 头里 4~8 是它自己的长度。
    只改长度字段，不动音频数据。
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data                     # 不是 WAV（比如通用服务返回 mp3）就原样返回

    buf = bytearray(data)
    pos = 12
    while pos + 8 <= len(buf):
        chunk_id = bytes(buf[pos:pos + 4])
        size = struct.unpack("<I", buf[pos + 4:pos + 8])[0]
        if chunk_id == b"data":
            buf[pos + 4:pos + 8] = struct.pack("<I", len(buf) - (pos + 8))
            buf[4:8] = struct.pack("<I", len(buf) - 8)
            return bytes(buf)
        if size == 0xFFFFFFFF:          # 结构不完整，别再往下走
            break
        pos += 8 + size + (size & 1)     # chunk 按偶数字节对齐
    return data


def _deepseek_tts(text: str) -> bytes:
    payload = {"text": text}
    if config.DEEPSEEK_TTS_VOICE:
        payload["voice"] = config.DEEPSEEK_TTS_VOICE

    resp = requests.post(
        config.DEEPSEEK_TTS_URL,
        headers={"Authorization": "Bearer " + config.DEEPSEEK_API_KEY,
                 "Content-Type": "application/json"},
        json=payload,
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise TTSUnavailable(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")
    if not resp.content:
        raise TTSUnavailable("TTS 返回空音频")
    return _fix_wav_sizes(resp.content)


def _generic_tts(text: str) -> bytes:
    """通用的 OpenAI 兼容 /audio/speech（备选，换供应商时用）"""
    payload = {"model": config.TTS_MODEL, "input": text}
    if config.TTS_VOICE:
        payload["voice"] = config.TTS_VOICE
    headers = {"Content-Type": "application/json"}
    if config.TTS_API_KEY:
        headers["Authorization"] = "Bearer " + config.TTS_API_KEY

    resp = requests.post(config.TTS_API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    if resp.status_code >= 400:
        raise TTSUnavailable(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")
    if not resp.content:
        raise TTSUnavailable("TTS 返回空音频")
    return _fix_wav_sizes(resp.content)


def synthesize(text: str) -> bytes:
    """把文字变成语音，返回音频字节（WAV）。不可用时抛 TTSUnavailable。"""
    text = (text or "").strip()
    if not text:
        raise TTSUnavailable("没有可朗读的文本")

    if config.DEEPSEEK_API_KEY:
        try:
            return _deepseek_tts(text)
        except TTSUnavailable:
            raise                        # 平台明确报错，直接降级
        except Exception as exc:         # noqa: BLE001 —— 网络类错误也降级
            raise TTSUnavailable(f"TTS 调用失败：{exc}") from exc

    if config.TTS_API_URL and config.TTS_MODEL:
        return _generic_tts(text)

    raise TTSUnavailable("未配置任何 TTS 服务")
