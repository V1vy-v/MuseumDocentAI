# 联调自测脚本（组员可用它验证自己的环境是否配好）
#
# 用法（在 backend/ 目录下，先启动服务）：
#   uvicorn app.main:app --port 8000
#   .venv\Scripts\python.exe scripts\smoke_test.py
#
# 它会依次测试：
#   1. 服务是否活着（/api/health）
#   2. 文本问答（/api/chat）
#   3. 语音闭环：用 TTS 造一句"提问语音" → 上传 /api/voice → 得到回答和播报语音

import base64
import json
import os
import sys
import tempfile
import urllib.request
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
    print("[1/3] 服务在线 ✓")


def step2_chat():
    r = requests.post(BACKEND + "/api/chat", timeout=90,
                      json={"question": "越王勾践剑是什么时期的文物？", "session_id": "smoke-test"})
    r.raise_for_status()
    data = r.json()
    print("[2/3] 文本问答 ✓")
    print("      回答:", data["answer"][:80])
    return data


def step3_voice():
    # 3a. 用 TTS 造一句提问语音（模拟观众说话）
    r = requests.post(MIMO_API_URL + "/chat/completions",
                      headers={"Authorization": "Bearer " + MIMO_KEY},
                      json={"model": "mimo-v2.5-tts",
                            "messages": [{"role": "assistant", "content": "你好，请问博物馆今天开放吗？"}]},
                      timeout=90)
    r.raise_for_status()
    wav = base64.b64decode(r.json()["choices"][0]["message"]["audio"]["data"])
    q_path = Path(tempfile.gettempdir()) / "smoke_question.wav"
    q_path.write_bytes(wav)
    print(f"[3/3] 已生成提问语音（{len(wav)} 字节）")

    # 3b. 上传给语音接口
    r = requests.post(BACKEND + "/api/voice", timeout=180,
                      files={"audio": ("question.wav", wav, "audio/wav")},
                      data={"session_id": "smoke-test"})
    r.raise_for_status()
    data = r.json()
    print("      识别到的提问:", data.get("question", "(无)"))
    print("      回答:", data["answer"][:80])
    if data.get("audio_base64"):
        a_path = Path(tempfile.gettempdir()) / "smoke_answer.wav"
        a_path.write_bytes(base64.b64decode(data["audio_base64"]))
        print(f"      播报语音已保存: {a_path}")
    print("[3/3] 语音闭环 ✓")


if __name__ == "__main__":
    step1_health()
    step2_chat()
    step3_voice()
    print("\n全部通过！前后端语音闭环正常。")
