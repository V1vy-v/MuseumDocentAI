# 【RAG】把知识库文档切成检索单元（chunk）
#
# 为什么必须切：老实现是"整篇文档取前 500 字"。
# 资料一长，后半篇永远检索不到，而且模型拿到的永远只有开头那段。
#
# 切分规则（按 Markdown 结构来，不按字数硬切）：
#   1. 按 # 标题分层，保留标题路径（"越王勾践剑 › 出土与年代"）
#   2. 同名小节内按空行分段，相邻段合并到 CHUNK_SIZE（300 字）
#   3. 单段超过 CHUNK_MAX（400 字）才硬切，留 CHUNK_OVERLAP（50 字）重叠，
#      避免答案正好卡在切点上
#   4. 丢掉引用块（> 提示语）和 HTML 注释 —— 它们是元信息，不是知识
#
# 产出：[{"heading": 标题路径, "chunk_no": 序号, "content": 正文}]

import re
from pathlib import Path

from ..core import config

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _body_lines(text: str) -> list:
    """去掉标题行、引用块、HTML 注释、代码围栏标记，返回正文行"""
    lines = []
    in_fence = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if not in_fence and _HEADING.match(stripped):
            continue
        if not in_fence and (stripped.startswith(">") or stripped.startswith("<!--")):
            continue
        lines.append(raw.rstrip())
    return lines


def _split_sections(text: str) -> list:
    """按标题把文档切成 [(标题路径, 正文行列表)]"""
    sections = []
    stack = []          # [(level, title)]
    current = []
    heading = ""

    def flush():
        if current:
            sections.append((heading, list(current)))
            current.clear()

    in_fence = False
    for raw in text.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(raw.strip())
        if match:
            flush()
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
            heading = " › ".join(title for _, title in stack)
            continue
        current.append(raw)
    flush()
    return sections


def _pack(paragraphs: list) -> list:
    """把段落合并成不超过 CHUNK_SIZE 的块；超长的再硬切"""
    merged = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if not buf:
            buf = para
        elif len(buf) + 1 + len(para) <= config.CHUNK_SIZE:
            buf += "\n" + para
        else:
            merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)

    chunks = []
    for block in merged:
        if len(block) <= config.CHUNK_MAX:
            chunks.append(block)
            continue
        # 硬切：步长 = 上限 - 重叠，最后一段直接收尾，避免产生大量碎片
        step = max(config.CHUNK_MAX - config.CHUNK_OVERLAP, 1)
        for start in range(0, len(block), step):
            piece = block[start:start + config.CHUNK_MAX].strip()
            if piece:
                chunks.append(piece)
            if start + config.CHUNK_MAX >= len(block):
                break
    return chunks


def split_text(text: str) -> list:
    """Markdown 正文 → chunk 列表（chunk_no 从 1 开始，同一次调用内连续）

    注意：块内容会带上所在小节标题（形如「故宫博物院 › 展厅分布与参观路线 › 参观信息」）。
    不带的话，"故宫开放时间"这类问题会命中卡片开头那段介绍，
    而真正写着开放时间的"参观信息"小节因为没有关键词上下文而排不上来。
    """
    if not text or not text.strip():
        return []

    out = []
    for heading, lines in _split_sections(text):
        body = _body_lines("\n".join(lines))
        for chunk in _pack(body):
            content = f"{heading}\n{chunk}" if heading else chunk
            out.append({"heading": heading, "chunk_no": len(out) + 1, "content": content})
    return out


def split_file(path: Path) -> list:
    """读一个知识库文件并切块；读不了就返回空（不让单个坏文件拖垮整个建库）"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return split_text(text)
