# 【角色 D 负责】会话管理接口的数据格式
#
# 为什么单独一个文件、而不是塞进 schemas/chat.py：
#   chat.py 里是 /api/chat、/api/voice 的契约，前端 ApiClient 已经按它解析了
#   （answer / sources / audio_base64）。那是**冻结的契约**，不要动现有字段。
#   这里放的是新增的会话管理能力，与前端已有代码无关。

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    """新建会话请求。

    session_id 可留空：留空由服务端生成，传了就沿用（前端现在是自己生成 UUID 的，
    保留这个入口是为了让它可以显式登记，而不是只能靠首次问答隐式建会话）。
    """
    session_id: str | None = None


class SessionCreateResponse(BaseModel):
    """新建会话响应"""
    session_id: str              # 会话编号，前端应存下来（SharedPreferences）
    created_at: str              # 创建时间（UTC ISO8601）
    existed: bool = False        # True 表示该编号本来就存在，直接沿用


class SessionSummary(BaseModel):
    """会话列表里的一项（只带展示需要的字段，不带消息正文）"""
    session_id: str
    title: str = ""              # 取首问，供列表展示
    created_at: str = ""
    updated_at: str = ""         # 最近一次活动，列表按它倒序
    message_count: int = 0


class SessionListResponse(BaseModel):
    """历史会话列表响应"""
    sessions: list[SessionSummary] = []
    count: int = 0


class SourceItem(BaseModel):
    """一条来源资料（带原文链接）。

    和流式响应 `meta.sources_detail` 的形状保持一致，前端可以复用同一套渲染。
    """
    title: str = ""
    heading: str = ""            # 命中的小节（历史消息里找不回来，会是空串）
    url: str = ""                # 原文地址，可直接点开；空串表示原文已不在
    score: float = 0.0           # 排序分（历史消息里是 0）


class MessageItem(BaseModel):
    """一条对话记录"""
    role: str                    # user / assistant
    content: str                 # 用户原话或模型回答（保真，未经改写）
    sources: list[str] = []      # 该轮回答引用的资料标题
    sources_detail: list[SourceItem] = []   # 同上，但带原文链接（前端做"点开看原文"用）
    created_at: str = ""
    resolved: str = ""           # 指代消解后的问句（诊断用，前端可忽略）
    tokens: int = 0              # 这条消息占多少 token（诊断用：上下文窗口就是按它算的）


class SessionMessagesResponse(BaseModel):
    """拉取历史响应"""
    session_id: str
    title: str = ""              # 取首问，供历史列表展示
    summary: str = ""            # 长对话滚动摘要（对话还短时为空串）
    created_at: str = ""
    updated_at: str = ""
    last_prompt_tokens: int = 0  # 最近一次请求的真实 prompt token 数（诊断用）
    messages: list[MessageItem] = []


class SessionDeleteResponse(BaseModel):
    """删除会话响应"""
    ok: bool = True
    deleted: bool = False        # False 表示本来就不存在（删除是幂等的，不算错误）
