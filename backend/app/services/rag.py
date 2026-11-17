# RAG 检索增强：回答博物馆问题时"有据可依"，减少模型瞎编（幻觉）。
#
#   retrieve(问题) -> [ {"title", "content", "heading", "path", "url", "score"}, ... ]
#
# 返回格式对调用方保持兼容：title / content 两个键一直都有，新增的键是附加信息
# （heading 小节、path 文件、url 原文链接），老代码只读 title/content 不受影响。
#
# 检索策略（两条路，优先级从高到低）：
#   1. zvec 向量库：向量距离闸门 + jieba/BM25 + RRF 融合（见 vector_store.py）
#   2. 关键词兜底：下面 _retrieve_keyword 的原始实现
#
# 为什么兜底只在"向量库不可用"时生效，而不是"向量库没命中"时：
#   实测「博物馆开放时间？」在关键词模式下会命中《越王勾践剑》，因为文档里
#   出现了"博物馆"三个字。向量库返回空就说明"确实没有相关资料"，
#   这时候再退回关键词，等于把假阳性又请回来。

import re
from pathlib import Path
from urllib.parse import quote

from ..core import config
from . import coreference, vector_store


def _url(rel_path: str) -> str:
    return config.KB_URL_PREFIX + quote(rel_path, safe="/")


def _retrieve_keyword(question: str) -> list:
    """【降级实现】2~3 字滑窗关键词匹配。

    保留它有两个用处：zvec 没装 / 没配 key 时服务仍然可用；
    以及出问题时能快速对比两条路的结果。

    已知缺陷（所以才有向量库）：无分词（"博物"+"物馆"算两次命中）、
    无 IDF、整篇只取前 500 字。
    """
    results = []
    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    if not kb_dir.exists():
        return results

    words = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        for n in (2, 3):
            words.update(run[i: i + n] for i in range(len(run) - n + 1))
    words.update(re.findall(r"[A-Za-z0-9]{2,}", question))
    if not words:
        return results

    for path in sorted(kb_dir.glob("**/*")):
        if path.suffix.lower() not in (".md", ".txt") or path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        hits = sum(1 for w in words if w in text or w in path.stem)
        if hits >= 2:
            rel = path.relative_to(kb_dir).as_posix()
            # 标题统一走 normalize_title：降级模式和向量模式必须给出同一个名字，
            # 否则前端会一会儿看到"示例_越王勾践剑"、一会儿看到"越王勾践剑"。
            results.append({"title": coreference.normalize_title(path.stem), "content": text[:500],
                            "heading": "", "path": rel, "url": _url(rel),
                            "score": float(hits), "_hits": hits})

    results.sort(key=lambda r: r["_hits"], reverse=True)
    for r in results:
        r.pop("_hits", None)
    return results[: config.TOP_K]


def retrieve(question: str, mode: str = "") -> list:
    """检索与问题相关的资料片段。

    返回的 title 是【文档级标题】（不是块编号）：
    它要进 ChatResponse.sources 给前端显示，也要给下一轮指代消解当焦点，
    所以同一篇文档的多个块命中后只保留最高分的那一个。

    mode 用于"A/B 对比"（课程演示要对比关键词与向量两条路的效果）：
      ""/"auto"  默认：有向量索引就走向量，出问题降级关键词
      "keyword"  强制关键词匹配（不调向量、不消耗 embedding 额度）
      "vector"   强制向量检索；索引没就绪时返回空，便于暴露问题而不是偷偷降级
    """
    if not (question or "").strip():
        return []

    mode = (mode or "").strip().lower()

    if mode == "keyword":
        return _retrieve_keyword(question)

    if mode == "vector":
        if not vector_store.available():
            return []
        return vector_store.search(question, topk=config.TOP_K)

    if vector_store.available():
        try:
            hits = vector_store.search(question, topk=config.TOP_K)
            # 命中就返回；没命中就返回空（代表"资料库确实没有"），不退回关键词
            return hits
        except Exception as exc:        # noqa: BLE001 —— 向量路出问题必须能兜住
            print("[rag] 向量检索失败，退回关键词模式：", type(exc).__name__, exc)

    return _retrieve_keyword(question)


def catalog() -> list:
    """馆藏资料清单（标题列表）。

    为什么需要它：「你们馆有什么文物」这类问题的答案就是【资料目录本身】，
    任何检索都返回不了 —— 检索是"在资料里找答案"，而这里问的是"有哪些资料"。
    所以把清单直接放进提示词，让模型知道自己手里有什么。

    不读索引，直接扫目录：这样向量库没就绪时也能用，而且永远是实时的
    （角色 C 新加一份资料，清单立刻多一条，不需要重建任何东西）。
    """
    titles = []
    for title, _ in _scan_kb():
        if title and title not in titles:
            titles.append(title)
    return titles


def _scan_kb() -> list:
    """扫知识库，返回 [(规范化标题, 相对路径)]"""
    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    if not kb_dir.exists():
        return []
    out = []
    for path in sorted(kb_dir.glob("**/*")):
        if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
            continue
        if path.name.upper() == "README.MD":
            continue
        out.append((coreference.normalize_title(path.stem),
                    path.relative_to(kb_dir).as_posix()))
    return out


def doc_index() -> dict:
    """标题 → 资料相对路径。

    同时登记"规范化标题"和"原始文件名"两种键：修复前存进库的老消息，
    标题还是带「示例_」前缀的原始文件名，只认一种键就会找不到原文。
    """
    index = {}
    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    for title, rel in _scan_kb():
        index.setdefault(title, rel)
        index.setdefault(Path(rel).stem, rel)
    return index


def sources_detail(titles) -> list:
    """把入库时只存下来的【标题】还原成带原文链接的来源列表。

    为什么需要：回答入库时只存了标题字符串（`sources` 列），`url` 是检索时
    现算的，没落库。所以 APP/调试台重启后回填历史时，如果不还原一下，
    来源气泡就退化成点不开的纯文本了。

    返回格式与流式 `meta.sources_detail` 完全一致，前端可以复用同一套渲染。
    heading 找不回来（它属于当次检索的上下文），留空即可。
    """
    index = doc_index()
    out = []
    for title in titles or []:
        rel = index.get(title, "")
        out.append({"title": title,
                    "heading": "",
                    "url": _url(rel) if rel else "",
                    "score": 0})
    return out
