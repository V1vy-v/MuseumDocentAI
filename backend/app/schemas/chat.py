# 【角色 D 负责】前后端数据格式约定
#
# 这里定义"接口收什么、回什么"，前端按这个格式解析，避免两边对不上。
# 与 app/api/、前端 net/ 包保持一致。

from pydantic import BaseModel

from .session import SourceItem


class ChatRequest(BaseModel):
    """文本问答请求"""
    question: str          # 问题文本
    session_id: str        # 会话编号（多轮对话靠它找历史）
    # 可选：强制指定检索方式，用于演示时对比两条路的效果。
    #   ""/"auto" 默认（有向量索引就走向量，否则关键词）
    #   "keyword" 只用关键词匹配   "vector" 只用向量检索
    # 老前端不传这个字段，行为与以前完全一致。
    retrieval: str = ""


class ChatResponse(BaseModel):
    """文本问答响应"""
    answer: str                      # 回答文本
    sources: list[str] = []          # 资料来源标题列表


class VoiceResponse(BaseModel):
    """语音问答响应"""
    question: str = ""               # 识别出的提问文本（供界面显示"我听到的是…"）
    answer: str                      # 回答文本（识别出的问题对应的回答）
    sources: list[str] = []          # 资料来源标题列表
    audio_base64: str = ""           # 回答的语音（base64 WAV），空串表示不播报
    # 新增的可选字段（不影响老前端）：sources 的增强版，带原文链接和小节，
    # 形状与 /api/chat/stream 的 meta.sources_detail 一致。
    sources_detail: list[SourceItem] = []


class ErrorResponse(BaseModel):
    """统一错误格式"""
    error: str                       # 错误说明（给开发看）
    hint: str                        # 给用户看的友好提示


class TtsRequest(BaseModel):
    """语音合成请求"""
    text: str                        # 要朗读的文本


class TtsResponse(BaseModel):
    """语音合成响应"""
    audio_base64: str = ""           # WAV 音频的 base64（可直接 data:audio/wav;base64, 播放）
    format: str = "wav"              # 音频格式，目前固定 wav
