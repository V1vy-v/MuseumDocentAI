# 【角色 D 负责】全局配置
#
# 所有"模型怎么连"的信息都集中放这里，换模型/换密钥只改这一个文件。
# 密钥从 backend/.env 读取（该文件已被 .gitignore 忽略，不会上传仓库）。

import os
from pathlib import Path

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parents[2]


def _load_env():
    """读取 backend/.env 里的 KEY=VALUE（不依赖第三方库）"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# —— 大脑模型：mimo 系列（同一平台，已实测可用）——
# 实测结论：
#   mimo-v2.5-asr   语音输入（听懂提问，返回文字）
#   mimo-v2.5-tts   语音输出（把回答变成语音，返回 base64 音频）
#   mimo-v2.6-flash 文本回答（快速；复杂问题可换 mimo-v2.5-pro）
MIMO_API_URL = os.environ.get("MIMO_API_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.environ.get("XIAOMI_API_KEY", "")
MIMO_ASR_MODEL = os.environ.get("MIMO_ASR_MODEL", "mimo-v2.5-asr")
MIMO_TEXT_MODEL = os.environ.get("MIMO_TEXT_MODEL", "mimo-v2.6-flash")
MIMO_TTS_MODEL = os.environ.get("MIMO_TTS_MODEL", "mimo-v2.5-tts")

# —— 服务设置 ——
HOST = "0.0.0.0"
PORT = 8000

# —— RAG 设置（角色 C 用）——
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
TOP_K = 3

# —— 讲解员人设（System Prompt）——
SYSTEM_PROMPT = (
    "你是一位专业、亲切的历史博物馆讲解员。"
    "请用口语化、简洁的中文回答观众的提问，适合语音播报，不要使用 Markdown 符号和列表编号。"
    "回答控制在150字以内，除非观众要求详细展开。"
)

# 防幻觉约定：检索不到资料时的回答
NO_KNOWLEDGE_REPLY = "抱歉，这个问题馆内资料暂未收录，您可以问问我馆藏文物、历史背景或展厅路线。"
