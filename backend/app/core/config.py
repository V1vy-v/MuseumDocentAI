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


def _float_env(name: str, default: float) -> float:
    """读一个浮点配置（阈值这类参数要能调，不该硬编码在代码里）"""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    """读一个整数配置，允许用环境变量覆盖（调参和调试用）。

    临时想验证长对话摘要时，不必改代码，启动前设一下就行：
        $env:SUMMARY_TRIGGER_TOKENS = "200"   # PowerShell
        SUMMARY_TRIGGER_TOKENS=200 uvicorn …  # bash
    值不合法时退回默认值，不让配置错误把服务带崩。
    """
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default

# —— 模型分工（全部走云端 OpenAI 兼容接口，无本地模型依赖）——
#   文本问答 / 摘要                  → DeepSeek deepseek-flash
#   语音识别                        → DeepSeek /v1/tools/asr
#   语音合成                        → DeepSeek /v1/tools/tts（返回 WAV）
#   文档向量化                      → 火山 Ark doubao-embedding-vision

# —— 文本大脑：DeepSeek（首选）——
# 实测（本机）：GET /models 给出 deepseek-flash / deepseek-v4-pro；
# deepseek-flash 默认会烧思考 token（completion 182 里 139 是思考），
# 加 thinking.type=disabled 后 reasoning 归零、耗时 1.81s → 1.20s。
# 注意 enable_thinking=false 对它【无效】，别用那个写法。
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_TEXT_MODEL = os.environ.get("DEEPSEEK_TEXT_MODEL", "deepseek-flash")
DEEPSEEK_DISABLE_THINKING = _int_env("DEEPSEEK_DISABLE_THINKING", 1) == 1

# 语音识别：DeepSeek 的工具接口（multipart 上传 file，返回 {"text": ...}）
# 实测响应：{"request_id": "...", "text": "...", "duration_ms": 1000}
DEEPSEEK_ASR_URL = os.environ.get("DEEPSEEK_ASR_URL",
                                  "https://api.deepseek.com/v1/tools/asr")

# —— 语音合成（DeepSeek /v1/tools/tts，实测可用）——
# 请求 {"text": "..."} → 返回 audio/wav（PCM 16bit 单声道 24kHz）。
# 实测耗时：3 字 1.5s、78 字 3.2s，大头是固定开销。
# 注意返回的是【流式 WAV】，长度字段是 0xFFFFFFFF，tts_client 会修正后再返回。
DEEPSEEK_TTS_URL = os.environ.get("DEEPSEEK_TTS_URL",
                                  "https://api.deepseek.com/v1/tools/tts")
DEEPSEEK_TTS_VOICE = os.environ.get("DEEPSEEK_TTS_VOICE", "")   # 留空用平台默认音色

# 备选：任意 OpenAI 兼容的 /audio/speech 服务（换供应商时填这几项即可）
TTS_API_URL = os.environ.get("TTS_API_URL", "")
TTS_API_KEY = os.environ.get("TTS_API_KEY", "")
TTS_MODEL = os.environ.get("TTS_MODEL", "")
TTS_VOICE = os.environ.get("TTS_VOICE", "")

# —— 文本大脑 + 向量：火山 Ark ——
# 实测（本机，2026）：
#   doubao-seed-2.1-lite    文本回答，OpenAI 兼容 /chat/completions，支持 stream
#   doubao-embedding-vision 向量，POST /embeddings，实测 2048 维
# 两者共用一个 API Key，但走同一个 base url。
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3")
ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
ARK_TEXT_MODEL = os.environ.get("ARK_TEXT_MODEL", "doubao-seed-2.1-lite")
ARK_EMBED_MODEL = os.environ.get("ARK_EMBED_MODEL", "doubao-embedding-vision")

# —— 向量化（独立配置，允许和文本模型不同家）——
# 不填 EMBED_* 就回落到上面的 Ark，所以老配置完全不受影响。
# 为什么单独拆出来：ARK_API_KEY/ARK_BASE_URL 同时是文本模型的备用通道
# （llm_client._text_target），把它们改指向别家会让备用通道悄悄失效。
#
# 实测（2026-11，本机，616 份资料 ≈ 3400 块）：
#   doubao-embedding-vision   2048 维，批量上限 10，约 2.1s/批，会 429
#   BAAI/bge-m3 (SiliconFlow) 1024 维，批量 512 仍可用，约 0.3s/批，未撞限频
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "").strip() or ARK_BASE_URL
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", "").strip() or ARK_API_KEY
EMBED_MODEL = os.environ.get("EMBED_MODEL", "").strip() or ARK_EMBED_MODEL

# doubao 默认会烧思考 token（实测一个寒暄烧了 469 个 reasoning token，
# completion 里 89% 是思考）。讲解场景延迟敏感，默认关掉；
# 万一平台不认这个参数，把开关置 0 即可，不影响其他调用。
ARK_DISABLE_THINKING = _int_env("ARK_DISABLE_THINKING", 1) == 1

# —— 服务设置 ——
# 监听地址由 uvicorn 命令行决定（--host/--port），这里只留端口用于启动日志打印。
PORT = 8000

# —— RAG / 向量库（zvec，进程内，无需服务端）——
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
TOP_K = 3

# 索引目录见下方 VECTOR_DIR（要等 DATA_DIR 定义好）
COLLECTION_NAME = "museum_kb"
EMBED_DIM = _int_env("EMBED_DIM", 2048)          # 首次建库会用真实返回值校准
EMBED_BATCH = _int_env("EMBED_BATCH", 100)       # 一次请求塞多少段
# 上限取决于供应商：火山 Ark 实测硬上限 10，SiliconFlow bge-m3 实测 512 仍可用。
# 平台有频率限制：Ark 按 0.4s/批会被 429 打断，批间留一点间隔最省事。
# 只影响首次建库/大幅增量，日常问答不受影响。
EMBED_DELAY_SECONDS = _float_env("EMBED_DELAY_SECONDS", 0.35)
EMBED_RETRIES = _int_env("EMBED_RETRIES", 6)     # 429/5xx 时的最大重试次数（指数退避）

# 分块：600 字目标、700 字上限、50 字重叠。
# 块大一点的目的很实际：新建库要调 500+ 次 embedding（平台限速约 10 次/分钟），
# 块从 300 调到 600 能把请求数砍掉一半（约 51 分钟 → 实测 513 次请求），检索质量几乎不降。
CHUNK_SIZE = _int_env("CHUNK_SIZE", 600)
CHUNK_MAX = _int_env("CHUNK_MAX", 700)
CHUNK_OVERLAP = _int_env("CHUNK_OVERLAP", 50)

# 检索：稠密取 50 个候选（小库下等于全扫，保证融合时每段都有距离可用）、
# FTS 取 20 个候选，再用 RRF 融合排序。
DENSE_CANDIDATES = _int_env("DENSE_CANDIDATES", 50)
FTS_CANDIDATES = _int_env("FTS_CANDIDATES", 20)
RRF_RANK_CONSTANT = _int_env("RRF_RANK_CONSTANT", 60)

# 相关性命中闸门：zvec 的 COSINE 返回的是【距离，越小越相似】。
# 超过这个距离视为不相关 —— 这是治"博物馆开放时间命中越王勾践剑"这类
# 假阳性的关键：光靠关键词，只要文档里出现"博物馆"三个字就会命中。
#
# 0.49 是在【当前 616 份资料的全国资料库】上重新标定的（doubao-embedding-vision，2048 维）：
#   正例①「越王勾践剑是什么时期」0.309、「曾侯乙编钟在哪个博物馆」0.275、
#        「故宫有什么名画」0.463、「兵马俑是哪个朝代」0.448、「那把刻着鸟篆的青铜剑」0.487
#         → 正例最高 0.487，取 0.49 刚好全部放行
#   负例「你好呀」0.500、「谢谢你」0.534、「Hello there」0.587、
#        「今天天气怎么样」0.595、「推荐一部电影」0.613 → 全部被挡在 0.49 之外
# 原来的 0.62 是"只有 1 份资料"时定的，资料变多后会放进大量弱相关来源
# （实测「Hello there」能检索到"景德镇瓷板画"），所以收紧到 0.49。
# 注意：距离阈值单独用会误杀——观众明确点名了某件文物时要无条件放行，
# 见 DENSE_ENTITY_BOOST。资料继续扩充后需要重新标定（每补约 10 份重标一次）。
#
# ⚠️ 这个阈值和向量化模型绑定，换了 EMBED_* 就必须重标：距离分布随模型变，
# 不同模型之间的 0.49 毫无可移植性。同一份资料换 bge-m3（1024 维）实测：
#   正例（最近候选距离）0.230 ~ 0.553，负例 0.394 ~ 0.540 —— 两者【重叠】，
#   不存在能干净分开的单一阈值。折中取 0.46：正例 14/15 放行、闲聊 5/15 漏放
#   （沿用 0.49 则是 14/15 放行、8/15 漏放）。追求更高召回可放宽到 0.49，
#   更干净的闲聊体验可收紧到 0.44，但会丢掉「甲骨文最早在哪里发现」这类问法。
# 所以用 bge-m3 时请在 .env 里覆盖 DENSE_MAX_DISTANCE，不要改这里的默认值。
DENSE_MAX_DISTANCE = _float_env("DENSE_MAX_DISTANCE", 0.49)

# 问题里明确点名了知识库里的某件文物（如"越王勾践剑在哪个展厅"）时，
# 该文物的资料直接视为相关，不再看距离。理由很朴素：
# 观众点名问的东西，馆里有它的资料，那就一定该拿出来——
# 这时候纠结语义距离只会把正确答案挡在门外。
DENSE_ENTITY_BOOST = _int_env("DENSE_ENTITY_BOOST", 1) == 1

# 资料原文的浏览地址（debug 界面把命中来源做成可点的小气泡）
KB_URL_PREFIX = "/api/kb/"

# 注入提示词的"资料清单"标题上限。
# 接入全国资料馆后资料有 4000+ 份，整份清单会让每次请求多出三四万 token；
# 只列前 N 个，其余用"等共 N 份资料"概括。设为 0 表示完全不注入清单。
CATALOG_MAX_TITLES = _int_env("CATALOG_MAX_TITLES", 120)

# —— 会话持久化与上下文窗口（角色 D 用）——
# 数据库落在 backend/data/chat.db，已在根 .gitignore 中排除，不会进仓库。
# 通过环境变量 CHAT_DB_PATH 可覆盖（单元测试用它指到临时文件）。
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("CHAT_DB_PATH", DATA_DIR / "chat.db"))

# zvec 索引目录：落在 backend/data 下（已被根 .gitignore 排除），可随时删掉重建。
# 注意 zvec 是【进程内】数据库，同一个目录只能被一个进程打开——
# 所以这个后端必须以单 worker 运行（uvicorn --workers 1，默认就是 1）。
VECTOR_DIR = Path(os.environ.get("VECTOR_DIR", DATA_DIR / "zvec_kb"))

# 总开关：置 0 则完全不建索引、不调 embedding 接口（单元测试和离线环境用）。
# 关掉后检索自动退回关键词模式，服务照常可用。
RAG_VECTOR_ENABLED = _int_env("RAG_VECTOR_ENABLED", 1) == 1

# —— 上下文窗口与长对话摘要（按 token 预算，而不是消息条数）——
# 为什么用 token 而不是条数：一条 500 字的资料和一句"嗯"都算一条消息，
# 按条数切窗口完全不准；token 才是真正的资源约束。
#
# 为什么窗口可以开这么大（历史实测数据，量级结论仍然成立）：
#   - 所用模型的上下文窗口在百万 token 量级，输入价格也很低
#     → 12000 token 的提示词成本可忽略；
#   - 提示词从 162 token 拉到 23598 token，耗时没有单调变差
#     （延迟主要由输出/思考 token 和平台波动决定，实测波动 1.5s~16.6s）；
#   - 前缀缓存生效：实测 cached_tokens 接近全量，重复前缀基本不重复计费。
# 所以窗口大小的依据不是"装不下"，而是"要不要留这么多原文"。
#
# 不需要分词器：
#   1. 各平台都在 usage 里返回真实用量，安全阀直接用服务端数字；
#   2. 中文经验值 1 个汉字 ≈ 1 个 token（实测 13 字 → 15 prompt_token，含模板开销）。
#   tiktoken 是 OpenAI 的词表，对这些模型本来就不准，还要加依赖，不用。
#
# 注意"窗口"和"触发阈值"是两件事：
#   窗口 = 保留多少原文；阈值 = 滑出窗口的部分攒到多少才压缩。
#   窗口 12000 之后，一次正常参观（30~60 问 ≈ 2200~4400 token）根本不会溢出，
#   所以阈值取小也不影响正常使用——它只在超长对话里生效。
RECENT_TOKEN_BUDGET = _int_env("RECENT_TOKEN_BUDGET", 12000)         # 最近多少 token 的对话原样喂给模型（约 160 轮）
SUMMARY_TRIGGER_TOKENS = _int_env("SUMMARY_TRIGGER_TOKENS", 1500)    # 滑出窗口且未被摘要覆盖的部分累积超过此值就压缩
SUMMARY_MAX_CHARS = _int_env("SUMMARY_MAX_CHARS", 400)               # 摘要文本长度上限（它也要占 prompt 预算）
PROMPT_TOKEN_ALERT = _int_env("PROMPT_TOKEN_ALERT", 200000)         # 整个提示词超过此值就告警（1M 上下文，留足余量）

# —— 会话治理 ——
# 增长只靠 TTL 控制：一轮问答约 200 字节，规模上完全不需要再设条数上限。
# （原先那个 MAX_MSG_PER_SESSION 定义了却从没被使用过，已删除——
#   留着会让人误以为有保护。）
SESSION_TTL_DAYS = 7

# —— 讲解员人设（System Prompt）——
# 定位：全国博物馆资料库（不是某一座博物馆）。所以不出现"本馆""我们馆"这类自称，
# 回答里被问到具体场馆信息时，以资料中写明的馆名为准。
SYSTEM_PROMPT = (
    "你是一位专业、亲切的博物馆讲解助手，掌握的是一批国内博物馆及其馆藏文物的公开资料。"
    "请用口语化、简洁的中文回答提问，适合语音播报，不要使用 Markdown 符号和列表编号。"
    "回答控制在150字以内，除非提问者要求详细展开。"
    "提到博物馆时用资料里的馆名，不要用「本馆」「我们馆」这类说法。"
    "资料里没有的信息（开放时间、门票、预约方式等）如实说明资料未收录，不要编造。"
)

# 防幻觉约定：检索不到资料时的回答
NO_KNOWLEDGE_REPLY = "抱歉，资料库里暂时没有这部分内容。您可以换个说法，或者问问我收录的博物馆和馆藏文物。"
