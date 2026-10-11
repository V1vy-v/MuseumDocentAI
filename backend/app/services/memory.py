# 【角色 D 负责】多轮对话记忆
#
# 目标：记得住上文，实现自然的连续对话（对应课题的"上下文记忆"要求）。
# 当前是最简版本：存在内存里，服务重启就清空（课程演示够用）。
# 后续升级方向：存到文件/数据库、指代消解、长对话摘要压缩。

from collections import defaultdict

# 会话存储：{ 会话编号: [{"role": "user"/"assistant", "content": "..."}] }
_SESSIONS = defaultdict(list)

# 每个会话最多保留的对话条数（滑动窗口）
MAX_TURNS = 20


def remember(session_id: str, role: str, content: str):
    """记一条对话"""
    turns = _SESSIONS[session_id]
    turns.append({"role": role, "content": content})
    if len(turns) > MAX_TURNS:
        del turns[: len(turns) - MAX_TURNS]


def recall(session_id: str) -> list:
    """取该会话的对话历史（给模型看的上文）"""
    return list(_SESSIONS.get(session_id, []))
