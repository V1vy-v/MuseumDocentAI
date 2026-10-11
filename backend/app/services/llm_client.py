# 【角色 D 负责】封装 mimo 模型调用
#
# 这是"大脑"的唯一入口，其他文件都通过这里和模型说话。
# 已实测的调用格式（OpenAI 兼容接口，地址见 core/config.py）：
#   文本问答：POST /chat/completions，标准 messages 格式
#   语音识别：POST /chat/completions，用户消息里带 input_audio（base64 WAV）
#   语音合成：POST /chat/completions，messages 里含 assistant 角色的文本，
#             回复的 message.audio.data 里是 base64 音频

import base64

import requests

from ..core import config

_TIMEOUT = 60  # 秒


def _headers():
    return {"Authorization": "Bearer " + config.MIMO_API_KEY, "Content-Type": "application/json"}


def _chat(messages, model):
    """统一的调用入口：失败抛异常，成功返回回答文字"""
    resp = requests.post(
        config.MIMO_API_URL + "/chat/completions",
        headers=_headers(),
        json={"model": model, "messages": messages},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def transcribe(wav_bytes: bytes) -> str:
    """语音识别：把录音（WAV）变成文字（mimo-v2.5-asr 的语音输入）"""
    payload_user = {
        "role": "user",
        "content": [{
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(wav_bytes).decode(), "format": "wav"},
        }],
    }
    return _chat([payload_user], config.MIMO_ASR_MODEL)


def chat_reply(question: str, history: list, sources: list) -> str:
    """文本回答：问题 + 对话历史 + 检索资料 → 讲解员式回答

    history: [{"role": "user"/"assistant", "content": "..."}]（由 memory 提供）
    sources: rag.retrieve() 返回的资料片段 [{"title","content"}]
    """
    system = config.SYSTEM_PROMPT
    if sources:
        material = "\n".join(f"《{s['title']}》：{s['content']}" for s in sources)
        system += "\n\n请参考以下馆内资料回答，不要编造资料里没有的内容：\n" + material
    else:
        system += (
            "\n\n本次没有检索到相关馆内资料。若问题与博物馆无关可正常闲聊；"
            "若被问到具体馆藏资料，回答：" + config.NO_KNOWLEDGE_REPLY
        )

    messages = [{"role": "system", "content": system}]
    messages += history[-10:]  # 只带最近10轮，防止太长
    messages.append({"role": "user", "content": question})
    return _chat(messages, config.MIMO_TEXT_MODEL)
