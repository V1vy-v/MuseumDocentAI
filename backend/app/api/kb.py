# 【RAG】知识库原文浏览
#
# GET /api/kb/{相对路径}  → 把 knowledge_base/ 里的资料渲染成一个简单网页
#
# 用途：debug 界面上，命中检索的每一条资料都会显示成一个灰色小气泡，
# 点开就是这个页面 —— 答辩时可以直接证明"这个回答确实有出处"。
#
# 安全：只允许读 knowledge_base/ 目录内部的文件（防 ../ 穿越）。
# 这个接口只读、无副作用，所以不进 OpenAPI schema（和 /debug 一样是工具接口）。

import html
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..core import config

router = APIRouter()

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 馆内资料</title>
<style>
  body {{ margin:0; background:#faf9f7; color:#23201c;
         font:15px/1.75 "PingFang SC","Microsoft YaHei",system-ui,sans-serif; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:28px 20px 60px; }}
  .bar {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
         font-size:12px; color:#8a8178; margin-bottom:16px; }}
  .tag {{ background:#f0ece7; border:1px solid #e3ddd5; border-radius:999px; padding:1px 9px; }}
  pre {{ white-space:pre-wrap; word-break:break-word; background:#fff;
        border:1px solid #e7e2db; border-radius:10px; padding:18px 20px; margin:0; }}
</style></head>
<body><div class="wrap">
  <div class="bar"><span class="tag">馆内资料</span><span>{path}</span></div>
  <pre>{body}</pre>
</div></body></html>
"""


# ================== 手动检索资料（不经过大模型）==================
#
# 前端"资料库"页面用这两个接口：观众可以不提问，直接搜"青铜剑""故宫"，
# 自己翻资料原文。好处很实在：
#   1. 演示时能证明"答案确实来自这些文件"，不是模型编的；
#   2. 模型不可用（没网/没额度）时，这个功能照样能用；
#   3. 检索过程不消耗任何 token。
#
# 注意：这两个路由必须定义在最后的 /api/kb/{rel_path:path} 之前，
# 否则 "search" 会被通配路由当成文件路径吃掉。

_SUFFIX = (".md", ".txt")


def _meta(rel: Path) -> dict:
    """从相对路径推出 省份 / 所属馆 / 资料类型。

    目录约定（导入资料库时定的）：
      museums/<省>/<馆>.md
      artifacts/<省>/<馆>/<文物>.md
    """
    parts = rel.parts
    is_artifact = "artifacts" in parts
    if is_artifact:
        museum = parts[-2] if len(parts) >= 2 else ""
        province = parts[-3] if len(parts) >= 3 else ""
    else:
        museum = rel.stem
        province = parts[-2] if len(parts) >= 2 else ""
    return {"kind": "artifact" if is_artifact else "museum",
            "province": province, "museum": museum, "category": ""}


def _category(text: str) -> str:
    """文物卡里的"类别"（青铜器/陶瓷/书画…），用于按类型筛选。

    博物馆卡没有这个字段，返回空串（筛选时按"全部"处理）。
    """
    m = re.search(r"\*\*类别\*\*[：:]\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _snippet(text: str, words: set, width: int = 90) -> str:
    """截一段包含关键词的摘要，方便在列表里判断是不是想找的资料。

    要点：先丢掉 H1 标题行——列表里已经显示标题了，摘要再重复一遍毫无价值，
    而且博物馆卡正文第一行就是 "# 上海博物馆"，会截出"…"这种没用的结果。
    """
    body = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", ">"))
            and "编号" not in ln and not ln.startswith("馆藏：")]
    plain = re.sub(r"[*>_`\[\]()!]", " ", " ".join(body))
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""

    pos = -1
    for w in words:
        pos = plain.find(w)
        if pos >= 0:
            break
    if pos < 0:
        return plain[:width]
    start = max(0, pos - width // 3)
    return ("…" if start else "") + plain[start:start + width] + ("…" if start + width < len(plain) else "")


def _words(q: str) -> set:
    """中文按 2~3 字滑窗切，英文数字按词切——和关键词检索保持同一套口径。"""
    out = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", q):
        for n in (2, 3):
            out.update(run[i:i + n] for i in range(len(run) - n + 1))
    out.update(re.findall(r"[A-Za-z0-9]{2,}", q))
    return out


@router.get("/api/kb/search")
def kb_search(q: str = Query("", description="关键词；留空则按条件浏览"),
              kind: str = Query("", description="museum / artifact；留空=全部"),
              province: str = Query("", description="省份，如 湖北省；留空=全部"),
              category: str = Query("", description="文物类别，如 青铜器；留空=全部"),
              limit: int = Query(30, ge=1, le=200),
              offset: int = Query(0, ge=0, description="分页起点")):
    """检索知识库，返回标题+摘要+筛选维度（不调用任何模型）。

    返回里的 facets 是"筛选项 + 各自数量"，前端拿它渲染省份/类别的选项，
    不用再单独请求一次；数量会跟着当前的关键词/类型动态变化。
    """
    root = Path(config.KNOWLEDGE_BASE_DIR)
    if not root.exists():
        return {"query": q, "total": 0, "offset": offset, "limit": limit,
                "items": [], "facets": {"provinces": [], "categories": []}}

    words = _words(q)
    matched = []        # 过了"关键词 + 类型"的资料（facets 也从这里统计）
    for path in root.rglob("*"):
        if path.suffix.lower() not in _SUFFIX or path.name.upper() == "README.MD":
            continue
        # "示例_" 开头的文件是单元测试用的固定样例（示例_越王勾践剑.md），
        # 只给程序用，不该出现在给用户看的资料列表里。
        if path.stem.startswith("示例"):
            continue
        rel = path.relative_to(root)
        meta = _meta(rel)
        if kind and meta["kind"] != kind:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        title = path.stem

        if words:
            hits = sum(1 for w in words if w in text or w in title)
            # 短查询（如"故宫"只切出 1 个片段）不能要求命中 2 个，否则永远搜不到
            if hits < min(2, len(words)):
                continue
            score = hits + (10 if any(w in title for w in words) else 0)
        else:
            score = 0

        if meta["kind"] == "artifact":
            meta["category"] = _category(text)
        matched.append({
            "title": title, "path": rel.as_posix(), "score": score,
            "kind": meta["kind"], "province": meta["province"],
            "museum": meta["museum"], "category": meta["category"],
            "snippet": _snippet(text, words),
        })

    # 筛选维度：省份对所有资料统计；类别只对文物卡统计（博物馆卡没有类别）
    provinces = {}
    categories = {}
    for it in matched:
        if it["province"]:
            provinces[it["province"]] = provinces.get(it["province"], 0) + 1
        if it["category"]:
            categories[it["category"]] = categories.get(it["category"], 0) + 1

    def _facets(counter):
        return [{"name": k, "count": v}
                for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]

    # 按具体条件过滤
    items = [it for it in matched
             if (not province or it["province"] == province)
             and (not category or it["category"] == category)]

    # 有关键词按相关度排；没关键词按"博物馆优先 + 省份 + 名称"排
    if words:
        items.sort(key=lambda it: (-it["score"], it["title"]))
    else:
        items.sort(key=lambda it: (it["kind"] != "museum", it["province"], it["title"]))

    total = len(items)
    page = items[offset:offset + limit]
    return {"query": q, "total": total, "offset": offset, "limit": limit,
            "items": page,
            "facets": {"provinces": _facets(provinces), "categories": _facets(categories)}}


@router.get("/api/kb/filters")
def kb_filters():
    """资料库的筛选维度（进入页面时拿一次，避免空搜索时算两遍）。"""
    data = kb_search(q="", kind="", province="", category="", limit=1, offset=0)
    return data["facets"]


@router.get("/api/kb/doc")
def kb_doc(path: str = Query(..., description="相对 knowledge_base 的路径")):
    """取一份资料的纯文本，供 APP 直接渲染（不包 HTML）。"""
    root = Path(config.KNOWLEDGE_BASE_DIR).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404,
                            detail={"error": "knowledge doc not found", "hint": path})

    rel = target.relative_to(root)
    meta = _meta(rel)
    return {"title": target.stem, "path": rel.as_posix(),
            "text": target.read_text(encoding="utf-8", errors="ignore"), **meta}


# 通配路由放在最后：它会把 /api/kb/ 后面任何东西当文件路径，
# 所以前面那些具体路由（search / doc）必须先注册，否则永远轮不到它们。
@router.get("/api/kb/{rel_path:path}", include_in_schema=False)
def knowledge_doc(rel_path: str):
    root = Path(config.KNOWLEDGE_BASE_DIR).resolve()
    target = (root / rel_path).resolve()

    # is_relative_to 挡住 ../../.env 这类穿越；Python 3.9+ 才有，本项目跑 3.12
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404,
                            detail={"error": "knowledge doc not found", "hint": rel_path})

    text = target.read_text(encoding="utf-8", errors="ignore")
    return HTMLResponse(_PAGE.format(title=html.escape(target.stem),
                                     path=html.escape(rel_path),
                                     body=html.escape(text)))
