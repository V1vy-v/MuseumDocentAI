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
from pathlib import Path

from fastapi import APIRouter, HTTPException
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
