# 【角色 D 负责】封装 mimo 模型调用
#
# 这是"大脑"的唯一入口，其他文件都通过这里和模型说话。
# 已实测的调用格式（OpenAI 兼容接口，地址见 core/config.py）：
#   文本问答：POST /chat/completions，标准 messages 格式
#   语音识别：POST /chat/completions，用户消息里带 input_audio（base64 WAV）
#   语音合成：POST /chat/completions，messages 里含 assistant 角色的文本，
#             回复的 message.audio.data 里是 base64 音频
#
# 实测要点（写代码时别踩）：
#   1. 响应里带 usage，字段为 prompt_tokens / completion_tokens / total_tokens。
#      所以判断"上下文有多大"不需要自己分词，直接用服务端数字。
#   2. 这个模型会烧 reasoning token：让它回两个字，completion_tokens 是 19，
#      其中 16 个是思考。思考内容在 message.reasoning_content 里。
#      对语音这种延迟敏感的场景，这个开销要心里有数。

import base64
import json

import requests

from ..core import config

_TIMEOUT = 60              # 秒，非流式：整个请求的上限
_STREAM_TIMEOUT = (10, 60)  # 秒，(连接, 每次读)。流式下读超时是"多久没新数据才算卡死"


def _headers():
    return {"Authorization": "Bearer " + config.MIMO_API_KEY, "Content-Type": "application/json"}


def _chat_raw(messages, model) -> dict:
    """统一的调用入口：失败抛异常，成功返回整个响应体（含 usage）"""
    resp = requests.post(
        config.MIMO_API_URL + "/chat/completions",
        headers=_headers(),
        json={"model": model, "messages": messages},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _content(data: dict) -> str:
    return (data["choices"][0]["message"].get("content") or "").strip()


def _usage(data: dict) -> dict:
    """取服务端返回的用量；老接口没有这个字段时返回空字典"""
    return data.get("usage") or {}


def transcribe(wav_bytes: bytes) -> str:
    """语音识别：把录音（WAV）变成文字（mimo-v2.5-asr 的语音输入）"""
    payload_user = {
        "role": "user",
        "content": [{
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(wav_bytes).decode(), "format": "wav"},
        }],
    }
    return _content(_chat_raw([payload_user], config.MIMO_ASR_MODEL))


def _build_messages(question: str, history: list, sources: list, summary: str) -> list:
    """拼装发给模型的消息。

    chat_reply 和 stream_reply 共用一份，避免两条路径慢慢跑偏
    （历史上就吃过"改了一处忘了另一处"的亏）。
    """
    system = config.SYSTEM_PROMPT

    # 更早的对话已经被压缩成摘要，放在人设之后、资料之前
    if summary:
        system += "\n\n以下是本次对话更早部分的摘要，供你理解上下文：\n" + summary

    if sources:
        material = "\n".join(f"《{s['title']}》：{s['content']}" for s in sources)
        system += "\n\n请参考以下馆内资料回答，不要编造资料里没有的内容：\n" + material
    else:
        system += (
            "\n\n本次没有检索到相关馆内资料。若问题与博物馆无关可正常闲聊；"
            "若被问到具体馆藏资料，回答：" + config.NO_KNOWLEDGE_REPLY
        )

    messages = [{"role": "system", "content": system}]
    # 窗口截取已由 memory 按"轮"对齐完成，这里不再二次截断：
    # 原来那句 history[-10:] 会把一轮问答从中间切开，让模型看到没有提问的回答。
    messages += history
    messages.append({"role": "user", "content": question})
    return messages


def chat_reply(question: str, history: list, sources: list, summary: str = "") -> tuple:
    """文本回答：问题 + 历史摘要 + 对话历史 + 检索资料 → 讲解员式回答

    参数：
        question：观众本轮原话（不要传指代消解改写过的，模型要看到原话）
        history ：[{"role","content"}]，最近若干轮，已按轮对齐
        sources ：rag.retrieve() 返回的资料片段 [{"title","content"}]
        summary ：更早对话的压缩摘要，空串表示还没有

    返回：(回答文本, 用量字典)。用量来自服务端，用于安全阀和排查。
    """
    data = _chat_raw(_build_messages(question, history, sources, summary),
                     config.MIMO_TEXT_MODEL)
    return _content(data), _usage(data)


def stream_reply(question: str, history: list, sources: list, summary: str = ""):
    """流式版 chat_reply：逐块产出，最后产出用量。

    产出 (类型, 数据) 二元组：
        ("delta", 文本片段)
        ("usage", 用量字典)     —— 服务端在流末尾给；老接口可能没有

    实测（2026-10）：首字 1.85~3.03s，而整段要 24~30s。
    所以流式把"感知延迟"降了约 10 倍，总时长不变。

    改这个函数时别踩回这两个坑：
        1. iter_lines() 不要加 decode_unicode=True——响应头没声明 charset 时
           requests 会退回 latin-1 解码，中文全变乱码。要自己按 UTF-8 解字节。
        2. 流式下 timeout 是"每次读"的超时，不是整个请求的超时。
           所以 60 秒的含义变成"60 秒没有新数据才失败"，正合适。
    """
    payload = {"model": config.MIMO_TEXT_MODEL,
               "messages": _build_messages(question, history, sources, summary),
               "stream": True}
    resp = requests.post(config.MIMO_API_URL + "/chat/completions",
                         headers=_headers(), json=payload,
                         stream=True, timeout=_STREAM_TIMEOUT)
    resp.raise_for_status()

    for raw in resp.iter_lines():
        if not raw:                       # SSE 用空行分隔事件
            continue
        line = raw.decode("utf-8", errors="replace")
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            chunk = json.loads(body)
        except ValueError:
            continue                      # 半截的 JSON 行跳过，不让它打断整条流
        for choice in chunk.get("choices") or []:
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield ("delta", piece)
        if chunk.get("usage"):
            yield ("usage", chunk["usage"])


def summarize(old_summary: str, turns: list) -> str:
    """把较早的一批对话压成一段摘要（长对话滚动摘要用）。

    old_summary 非空表示这是"合并"：在上一次摘要的基础上并入新对话，
    而不是重头总结。这样每次只处理新增的一小段，省 token 也更稳定。

    turns：[{"role","content"}]，已滑出上下文窗口、且还没被摘要覆盖的那批。
    """
    lines = []
    for msg in turns:
        who = "观众" if msg.get("role") == "user" else "讲解员"
        lines.append(f"{who}：{msg.get('content', '')}")

    parts = [
        "你在为一段博物馆导览对话做压缩存档，把下面的对话压成一段简短摘要。",
        "必须保留：观众问过哪几件文物、问过哪些具体问题、"
        "以及关键的事实结论（年代、出土地、展厅位置）。",
        f"用一段连续的话，不超过 {config.SUMMARY_MAX_CHARS} 字，"
        "不要列表、不要标题、不要 Markdown 符号。",
    ]
    if old_summary:
        parts.append("这是已有摘要（它覆盖了更早的对话），请把新对话合并进去，"
                     "输出完整的合并结果：\n" + old_summary)
    parts.append("需要并入的新对话：\n" + "\n".join(lines))

    data = _chat_raw([{"role": "user", "content": "\n\n".join(parts)}],
                     config.MIMO_TEXT_MODEL)
    return _content(data)
