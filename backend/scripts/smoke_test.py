# 联调自测脚本（组员可用它验证自己的环境是否配好）
#
# 用法（在 backend/ 目录下，先启动服务）：
#   uvicorn app.main:app --port 8000
#   .venv\Scripts\python.exe scripts\smoke_test.py
#
# 它会依次测试：
#   1. 服务是否活着（/api/health）
#   2. 文本问答（/api/chat）—— 完整问句
#   3. 多轮记忆 + 指代消解 —— 同一会话里用「它」追问，必须仍能检索到资料
#   4. 语音闭环：用 TTS 造一句"提问语音" → 上传 /api/voice → 得到回答和播报语音
#
# 第 3 步是关键回归项：改造前 /api/chat 是先检索再取历史，用带代词的原文去检索
# 必然命中为空，模型会回答「馆内资料暂未收录」——上一轮刚讲过，观众却觉得机器人失忆。

import base64
import json
import os
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

# 读取模型配置（造测试语音用）
env = {}
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="ascii", errors="ignore").splitlines():
        if "=" in line:
            k, v = line.strip().split("=", 1)
            env[k] = v
MIMO_API_URL = env.get("MIMO_API_URL", "")
MIMO_KEY = env.get("XIAOMI_API_KEY", "")


def step1_health():
    r = requests.get(BACKEND + "/api/health", timeout=10)
    assert r.json()["status"] == "ok", r.text
    print("[1/4] 服务在线 ✓")


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
    # 4a. 用 TTS 造一句提问语音（模拟观众说话）
    r = requests.post(MIMO_API_URL + "/chat/completions",
                      headers={"Authorization": "Bearer " + MIMO_KEY},
                      json={"model": "mimo-v2.5-tts",
                            "messages": [{"role": "assistant", "content": "你好，请问博物馆今天开放吗？"}]},
                      timeout=90)
    r.raise_for_status()
    wav = base64.b64decode(r.json()["choices"][0]["message"]["audio"]["data"])
    q_path = Path(tempfile.gettempdir()) / "smoke_question.wav"
    q_path.write_bytes(wav)
    print(f"[4/4] 已生成提问语音（{len(wav)} 字节）")

    # 4b. 上传给语音接口
    r = requests.post(BACKEND + "/api/voice", timeout=180,
                      files={"audio": ("question.wav", wav, "audio/wav")},
                      data={"session_id": "smoke-voice-" + uuid.uuid4().hex[:8]})
    r.raise_for_status()
    data = r.json()
    print("      识别到的提问:", data.get("question", "(无)"))
    print("      回答:", data["answer"][:80])
    if data.get("audio_base64"):
        a_path = Path(tempfile.gettempdir()) / "smoke_answer.wav"
        a_path.write_bytes(base64.b64decode(data["audio_base64"]))
        print(f"      播报语音已保存: {a_path}")
    print("[4/4] 语音闭环 ✓")


if __name__ == "__main__":
    step1_health()
    session_id = step2_chat()
    step3_multiturn(session_id)
    step4_voice()
    print("\n全部通过！文本、多轮指代、语音闭环均正常。")
