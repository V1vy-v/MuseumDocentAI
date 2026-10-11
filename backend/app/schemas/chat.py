# 【角色 D 负责】前后端数据格式约定
#
# 这里定义"接口收什么、回什么"，前端按这个格式解析，避免两边对不上。
# 与 app/api/、前端 net/ 包保持一致。

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """文本问答请求"""
    question: str          # 问题文本
    session_id: str        # 会话编号（多轮对话靠它找历史）


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


class ErrorResponse(BaseModel):
    """统一错误格式"""
    error: str                       # 错误说明（给开发看）
    hint: str                        # 给用户看的友好提示
