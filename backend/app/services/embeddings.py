# 【RAG】向量化：调火山 Ark 的 doubao-embedding-vision
#
# 为什么不用本地模型：本地 sentence-transformers 要拖 2~3 GB 的 torch，
# 而这个项目的向量化量很小（几十段文本），不值得为此把部署体积翻十倍。
# Ark 这条路零本地依赖，接口是 OpenAI 兼容的：
#   POST {ARK_BASE_URL}/embeddings  {"model": ..., "input": [文本, ...]}
#   → {"data": [{"index": 0, "embedding": [2048 个 float]}, ...], "usage": {...}}
#
# 实测（本机）：一次请求可以带多段文本，返回 2048 维。
# 注意返回的 data 不保证顺序 —— 按 index 排回去，否则向量和文本会错配。

import requests

from ..core import config

_TIMEOUT = 60


class EmbeddingError(RuntimeError):
    """向量化失败。调用方应当降级到关键词检索，而不是让整个问答挂掉。"""


def available() -> bool:
    """有没有配置 key。没配就走降级路径。"""
    return bool(config.ARK_API_KEY)


def _headers() -> dict:
    return {"Authorization": "Bearer " + config.ARK_API_KEY,
            "Content-Type": "application/json"}


def _embed_batch(texts: list) -> list:
    """一次 HTTP 请求做一批，返回与 texts 顺序一致的向量列表"""
    if not texts:
        return []
    if not config.ARK_API_KEY:
        raise EmbeddingError("未配置 ARK_API_KEY")

    resp = requests.post(
        config.ARK_BASE_URL.rstrip("/") + "/embeddings",
        headers=_headers(),
        json={"model": config.ARK_EMBED_MODEL, "input": texts},
        timeout=_TIMEOUT,
    )
    if resp.status_code >= 400:
        # 把平台返回的原文带出来，否则排查时只能看到 400
        raise EmbeddingError(f"embedding HTTP {resp.status_code}: {resp.text[:300]}")

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
    """文档批量向量化（按 EMBED_BATCH 分批，避免一次请求过大）"""
    out = []
    batch = max(config.EMBED_BATCH, 1)
    for start in range(0, len(texts), batch):
        out.extend(_embed_batch(texts[start:start + batch]))
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
