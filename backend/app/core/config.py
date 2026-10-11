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

# —— 会话持久化与上下文窗口（角色 D 用）——
# 数据库落在 backend/data/chat.db，已在根 .gitignore 中排除，不会进仓库。
# 通过环境变量 CHAT_DB_PATH 可覆盖（单元测试用它指到临时文件）。
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("CHAT_DB_PATH", DATA_DIR / "chat.db"))

# —— 上下文窗口与长对话摘要（按 token 预算，而不是消息条数）——
# 为什么用 token 而不是条数：一条 500 字的资料和一句"嗯"都算一条消息，
# 按条数切窗口完全不准；而 token 才是真正的资源约束（成本和上下文上限）。
#
# 这里不需要分词器：
#   1. mimo 接口在 usage 里返回真实用量，安全阀直接用服务端数字；
#   2. 中文经验值 1 个汉字 ≈ 1 个 token（实测 13 字 → 15 prompt_token，含模板开销），
#      估算只用于"何时压缩"，宁可略大（早压缩是安全方向）。
#   tiktoken 是 OpenAI 的词表，对 mimo 本来就不准，还要加依赖，不用。
RECENT_TOKEN_BUDGET = 1200     # 最近多少 token 的对话原样喂给模型
SUMMARY_TRIGGER_TOKENS = 2400  # 滑出窗口且未被摘要覆盖的部分累积超过此值才压缩一次
SUMMARY_MAX_CHARS = 400        # 摘要文本长度上限（它也要占 prompt 预算）
PROMPT_TOKEN_ALERT = 6000      # 整个提示词超过此值就告警：说明光压历史已不够用

# —— 会话治理 ——
MAX_MSG_PER_SESSION = 500
SESSION_TTL_DAYS = 7

# —— 讲解员人设（System Prompt）——
SYSTEM_PROMPT = (
    "你是一位专业、亲切的历史博物馆讲解员。"
    "请用口语化、简洁的中文回答观众的提问，适合语音播报，不要使用 Markdown 符号和列表编号。"
    "回答控制在150字以内，除非观众要求详细展开。"
)

# 防幻觉约定：检索不到资料时的回答
NO_KNOWLEDGE_REPLY = "抱歉，这个问题馆内资料暂未收录，您可以问问我馆藏文物、历史背景或展厅路线。"
