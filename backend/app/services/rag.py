# 【角色 C 负责】RAG 检索增强（当前为占位实现，供联调先行）
#
# 目标：回答博物馆问题时"有据可依"，减少模型瞎编（幻觉）。
#
#   retrieve(问题) -> [ {"title": 来源标题, "content": 资料片段}, ... ]
#
# 当前实现：直接在 knowledge_base/ 的文本文件里做简单的关键词匹配。
# 角色 C 后续替换为：查询改写 + 向量检索（FAISS/Chroma）+ 资料切分。
# 不论谁实现，只要保持 retrieve(问题) 的返回格式不变，其他模块不用改。

import re
from pathlib import Path

from ..core import config


def retrieve(question: str) -> list:
    """检索与问题相关的资料片段（占位：关键词匹配）"""
    results = []
    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    if not kb_dir.exists():
        return results

    # 把问题里的词拆出来当关键词（很粗暴，够联调用）
    words = [w for w in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", question) if w]
    for path in sorted(kb_dir.glob("**/*")):
        if path.suffix.lower() not in (".md", ".txt") or path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        # 命中任意关键词就收录（按命中数排序）
        hits = sum(1 for w in words if w in text or w in path.stem)
        if hits > 0:
            results.append({"title": path.stem, "content": text[:500], "_hits": hits})

    results.sort(key=lambda r: r["_hits"], reverse=True)
    for r in results:
        r.pop("_hits", None)
    return results[: config.TOP_K]
