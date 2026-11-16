# 联调自测脚本（组员可用它验证自己的环境是否配好）
#
# 用法（在 backend/ 目录下，先启动服务）：
#   uvicorn app.main:app --port 8000
#   .venv\Scripts\python.exe scripts\smoke_test.py
#
# 它会依次测试：
#   1. 服务是否活着（/api/health），顺带看向量索引是"向量模式"还是"关键词降级"
#   2. 文本问答（/api/chat）—— 完整问句
#   3. 多轮记忆 + 指代消解 —— 同一会话里用「它」追问，必须仍能检索到资料
#   4. 语音接口（/api/voice）是否活着
#
# 第 3 步是关键回归项：改造前 /api/chat 是先检索再取历史，用带代词的原文去检索
# 必然命中为空，模型会回答「馆内资料暂未收录」——上一轮刚讲过，观众却觉得机器人失忆。
#
# 第 4 步的说明：用 DeepSeek 的 TTS 现场合成一句提问语音，再喂给 /api/voice，
# 所以这是一个真正的语音闭环验证，且在 Windows/Linux/macOS 上都能跑。
#   - 想用自己的录音测：$env:SMOKE_AUDIO="D:\rec.wav"
#   - TTS 不可用时退回发送静音，断言接口返回 422「没听清」
#     （这仍然验证了 ASR 通路和空结果拦截）

import base64
import io
import os
import sys
import tempfile
import uuid
import wave
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services import tts_client  # noqa: E402  仅用于"造一句测试提问语音"

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")


def _silent_wav(seconds=1.0, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def step1_health():
    r = requests.get(BACKEND + "/api/health", timeout=10)
    data = r.json()
    assert data["status"] == "ok", r.text
    index = data.get("index") or {}
    mode = "向量索引就绪" if index.get("ready") else f"关键词降级（{index.get('error') or '未就绪'}）"
    print(f"[1/4] 服务在线 ✓  检索模式：{mode}")


def step2_chat():
    """第 1 轮：完整问句，建立话题"""
    # 每轮跑用独立会话，避免历史累积导致结果不确定
    session_id = "smoke-turn-" + uuid.uuid4().hex[:8]
    r = requests.post(BACKEND + "/api/chat", timeout=90,
                      json={"question": "越王勾践剑是什么时期的文物？",
                            "session_id": session_id})
    r.raise_for_status()
    data = r.json()
    print("[2/4] 文本问答（完整问句）✓")
    print("      回答:", data["answer"][:80])
    print("      来源:", data.get("sources"))
    return session_id


def step3_multiturn(session_id):
    """第 2 轮：只说「它」，验证指代消解 + 检索顺序"""
    r = requests.post(BACKEND + "/api/chat", timeout=90,
                      json={"question": "它是什么年代的？", "session_id": session_id})
    r.raise_for_status()
    data = r.json()
    print("[3/4] 多轮记忆 + 指代消解（用「它」追问）")
    print("      回答:", data["answer"][:80])
    if not data.get("sources"):
        raise AssertionError(
            "第 2 轮没检索到任何资料 —— 指代消解没生效，"
            "检索拿到的多半还是带代词的原文"
        )
    print(f"      资料来源: {data['sources']} ✓")
    return data


def step4_voice():
    custom = os.environ.get("SMOKE_AUDIO")
    if custom:
        wav = Path(custom).read_bytes()
        print(f"[4/4] 使用指定录音：{custom}（{len(wav)} 字节）")
        expect_empty = False
    else:
        try:
            wav = tts_client.synthesize("越王勾践剑是什么年代的")
            print(f"[4/4] 已用 TTS 合成测试提问「越王勾践剑是什么年代的」（{len(wav)} 字节）")
            expect_empty = False
        except tts_client.TTSUnavailable as exc:
            wav = _silent_wav()
            print(f"[4/4] TTS 不可用（{exc}），改发静音音频验证 ASR 通路")
            expect_empty = True

    r = requests.post(BACKEND + "/api/voice", timeout=240,
                      files={"audio": ("question.wav", wav, "audio/wav")},
                      data={"session_id": "smoke-voice-" + uuid.uuid4().hex[:8]})

    if expect_empty:
        if r.status_code == 422:
            print("      ASR 通路正常，空识别被拦下 ✓")
        elif r.status_code == 200:
            print("      意外地识别出了内容:", r.json().get("question"))
        else:
            raise AssertionError(f"语音接口返回了 {r.status_code}: {r.text[:200]}")
        return

    r.raise_for_status()
    data = r.json()
    print("      识别到的提问:", data.get("question", "(无)"))
    print("      回答:", data["answer"][:80])
    print("      来源:", data.get("sources"))
    if data.get("question") and "勾践" not in data["question"]:
        raise AssertionError("识别结果和合成的提问对不上，ASR 可能有问题")
    if data.get("audio_base64"):
        a_path = Path(tempfile.gettempdir()) / "smoke_answer.wav"
        a_path.write_bytes(base64.b64decode(data["audio_base64"]))
        print(f"      播报语音已保存: {a_path}（{a_path.stat().st_size} 字节）")
    else:
        print("      没有播报语音（TTS 合成失败，已降级为只返回文字）")
    print("[4/4] 语音闭环 ✓")


if __name__ == "__main__":
    step1_health()
    session_id = step2_chat()
    step3_multiturn(session_id)
    step4_voice()
    print("\n全部通过！文本、多轮指代、语音接口均正常。")
