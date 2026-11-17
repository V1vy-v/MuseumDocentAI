# 【RAG】向量化：调远端 embeddings 接口（OpenAI 兼容）
#
# 为什么不用本地模型：本地 sentence-transformers 要拖 2~3 GB 的 torch，
# 而这个项目的向量化量很小（几十段文本），不值得为此把部署体积翻十倍。
# 远端这条路零本地依赖，接口是 OpenAI 兼容的：
#   POST {EMBED_BASE_URL}/embeddings  {"model": ..., "input": [文本, ...]}
#   → {"data": [{"index": 0, "embedding": [...], ...}], "usage": {...}}
#
# 供应商可换（见 config.EMBED_*）：火山 doubao-embedding-vision（2048 维、
# 批量上限 10、会 429）或 SiliconFlow BAAI/bge-m3（1024 维、批量可到 512、
# 实测不限频）。两家的价格/维度/限频差很多，所以批量大小做成可配。
#
# 注意返回的 data 不保证顺序 —— 按 index 排回去，否则向量和文本会错配。

import time

import requests

from ..core import config

_TIMEOUT = 60


class EmbeddingError(RuntimeError):
    """向量化失败。调用方应当降级到关键词检索，而不是让整个问答挂掉。"""


def available() -> bool:
    """有没有配置 key。没配就走降级路径。"""
    return bool(config.EMBED_API_KEY)


def _headers() -> dict:
    return {"Authorization": "Bearer " + config.EMBED_API_KEY,
            "Content-Type": "application/json"}


def _embed_batch(texts: list) -> list:
    """一次 HTTP 请求做一批，返回与 texts 顺序一致的向量列表

    有的供应商有频率限制（实测 Ark 大批量建库会返回 429
    AccountRateLimitExceeded），所以这里遇到 429/5xx 就指数退避重试，
    而不是让整个建库失败。
    """
    if not texts:
        return []
    if not config.EMBED_API_KEY:
        raise EmbeddingError("未配置 EMBED_API_KEY（也未配置 ARK_API_KEY）")

    attempts = max(config.EMBED_RETRIES, 1)
    last_error = ""
    resp = None
    for attempt in range(attempts):
        resp = requests.post(
            config.EMBED_BASE_URL.rstrip("/") + "/embeddings",
            headers=_headers(),
            json={"model": config.EMBED_MODEL, "input": texts},
            timeout=_TIMEOUT,
        )
        if resp.status_code < 400:
            break
        if resp.status_code == 429 or resp.status_code >= 500:
            # 退避：1,2,4,8,16,30 秒（上限 30）
            wait = min(2 ** attempt, 30)
            last_error = f"embedding HTTP {resp.status_code}: {resp.text[:200]}"
            # 带上状态码：不然日志里分不清是 429 限频还是 5xx 服务故障
            print(f"[向量化] HTTP {resp.status_code} 需重试，{wait}s 后重试（{attempt + 1}/{attempts}）", flush=True)
            time.sleep(wait)
            continue
        # 其它 4xx 是请求本身有问题，重试没用
        raise EmbeddingError(f"embedding HTTP {resp.status_code}: {resp.text[:300]}")
    else:
        raise EmbeddingError(f"embedding 重试 {attempts} 次仍失败：{last_error}")

    try:
        data = resp.json().get("data") or []
    except ValueError as exc:
        raise EmbeddingError(f"embedding 返回不是合法 JSON: {exc}") from exc

    if len(data) != len(texts):
        raise EmbeddingError(f"embedding 返回条数不符：要 {len(texts)} 条，拿到 {len(data)} 条")

    data.sort(key=lambda item: item.get("index", 0))
    vectors = []
    for item in data:
        vector = item.get("embedding")
        if not vector:
            raise EmbeddingError("embedding 返回里有空向量")
        vectors.append(vector)
    return vectors


def embed_documents(texts: list) -> list:
    """文档批量向量化（按 EMBED_BATCH 分批，批间留间隔避开频率限制）

    建库时这里要跑几百次网络请求，所以每批都打一行进度。
    否则日志里只有"卡住"和"完成"两种状态，出问题没法判断进展到哪了。
    """
    out = []
    batch = max(config.EMBED_BATCH, 1)
    delay = max(getattr(config, "EMBED_DELAY_SECONDS", 0.0), 0.0)
    total = len(texts)
    started = time.time()
    for start in range(0, total, batch):
        if start and delay:
            time.sleep(delay)
        out.extend(_embed_batch(texts[start:start + batch]))
        done = min(start + batch, total)
        print(f"[向量化] {done}/{total} 段  已用 {time.time() - started:.1f}s", flush=True)
    return out


def embed_query(text: str) -> list:
    """查询向量化。空查询直接报错，别把空串喂给平台。"""
    text = (text or "").strip()
    if not text:
        raise EmbeddingError("查询为空")
    return _embed_batch([text])[0]


def dimension() -> int:
    """探测真实维度。

    zvec 的集合必须在创建时写死维度，所以不能靠猜：
    建库前先向量化一句话，用返回长度当维度。
    """
    return len(embed_query("维度探测"))
