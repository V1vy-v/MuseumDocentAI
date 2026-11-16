# 【角色 D 负责】封装大模型调用
#
# 这是"大脑"的唯一入口，其他文件都通过这里和模型说话。
# 现有分工（都是 OpenAI 兼容接口，地址见 core/config.py）：
#   文本问答 / 摘要 → DeepSeek deepseek-flash（POST /chat/completions）
#   语音识别        → DeepSeek /v1/tools/asr（multipart 上传，返回 {"text": ...}）
#
# 实测要点（写代码时别踩）：
#   1. 响应里带 usage，字段为 prompt_tokens / completion_tokens / total_tokens。
#      所以判断"上下文有多大"不需要自己分词，直接用服务端数字。
#   2. 这类模型默认会烧 reasoning token：让它回一句话，completion 里八九成是思考。
#      对语音这种延迟敏感的场景必须关掉——deepseek-flash 实测从 1.81s 降到 1.20s。
#      关法是 thinking={"type":"disabled"}；
#      enable_thinking=false 是【无效】的写法，别用。

import json

import requests

from ..core import config
from . import guard

_TIMEOUT = 60              # 秒，非流式：整个请求的上限
_STREAM_TIMEOUT = (10, 60)  # 秒，(连接, 每次读)。流式下读超时是"多久没新数据才算卡死"


def _headers(key: str) -> dict:
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}


def _text_target() -> dict:
    """文本大脑走哪家，按配置优先级从高到低：DeepSeek → 火山 Ark。

    两家都是 OpenAI 兼容接口，所以只换 url/key/model，调用代码一份就够。
    这样任何一家出问题或额度用完，改 .env 一行就能切走，不用动代码。
    """
    # 实测：这两家都认 thinking.type=disabled。
    no_think = {"thinking": {"type": "disabled"}}

    if config.DEEPSEEK_API_KEY:
        return {
            "url": config.DEEPSEEK_BASE_URL,
            "key": config.DEEPSEEK_API_KEY,
            "model": config.DEEPSEEK_TEXT_MODEL,
            "extra": no_think if config.DEEPSEEK_DISABLE_THINKING else None,
            # 流式下默认不返回 usage，要显式要；不然 token 记账会一直是空的
            "stream_options": {"include_usage": True},
        }
    if config.ARK_API_KEY:
        return {
            "url": config.ARK_BASE_URL,
            "key": config.ARK_API_KEY,
            "model": config.ARK_TEXT_MODEL,
            "extra": no_think if config.ARK_DISABLE_THINKING else None,
            "stream_options": None,
        }
    raise RuntimeError("没有配置任何文本模型密钥：请在 backend/.env 里填 DEEPSEEK_API_KEY")


def _post_chat(messages, model, url, key, extra=None) -> dict:
    """统一的调用入口：失败抛异常，成功返回整个响应体（含 usage）"""
    payload = {"model": model, "messages": messages}
    if extra:
        payload.update(extra)
    resp = requests.post(
        url.rstrip("/") + "/chat/completions",
        headers=_headers(key),
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _chat_raw(messages, model=None) -> dict:
    """文本模型调用（具体走哪家由 _text_target 决定）"""
    target = _text_target()
    return _post_chat(messages, model or target["model"],
                      target["url"], target["key"], target["extra"])


def _content(data: dict) -> str:
    return (data["choices"][0]["message"].get("content") or "").strip()


def _usage(data: dict) -> dict:
    """取服务端返回的用量；老接口没有这个字段时返回空字典"""
    return data.get("usage") or {}


def _deepseek_asr(wav_bytes: bytes) -> str:
    """DeepSeek 语音识别：POST /v1/tools/asr，multipart 字段名是 file。

    实测返回：{"request_id": "...", "text": "识别出的文字", "duration_ms": 1000}
    静音或听不清时 text 是空串（不是报错），调用方要自己判断空串。
    """
    resp = requests.post(
        config.DEEPSEEK_ASR_URL,
        headers={"Authorization": "Bearer " + config.DEEPSEEK_API_KEY},
        files={"file": ("speech.wav", wav_bytes, "audio/wav")},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"ASR 返回不是 JSON: {resp.text[:200]}") from exc
    return (data.get("text") or "").strip()


def transcribe(wav_bytes: bytes) -> str:
    """语音识别：把录音（WAV）变成文字（DeepSeek /v1/tools/asr）。"""
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法做语音识别")
    return _deepseek_asr(wav_bytes)


def _build_messages(question: str, history: list, sources: list, summary: str,
                    catalog: list = None) -> list:
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
        system += ("\n\n请参考以下馆内资料回答。资料里没有的信息"
                   "（开放时间、门票、地址等）不要编造，直接说明资料里没有：\n" + material)
    else:
        # 这段是防幻觉的关键。实测教训：原来的写法是"若与博物馆无关可正常闲聊"，
        # 结果模型把"博物馆开放时间""有哪些展厅"当成闲聊，
        # 编出了"周二到周日九点到五点""人之源/城之源"这种不存在的馆内信息。
        system += (
            "\n\n本次没有检索到相关馆内资料。"
            "凡是关于本馆的问题（开放时间、门票、展厅分布、参观路线、有哪些文物等）"
            "都属于馆内信息，必须明确说明资料暂未收录，绝对不要凭常识编造；"
            "只有与博物馆、文物、历史都无关的闲聊才可正常回应。"
            "馆内信息类问题统一这样回答：" + config.NO_KNOWLEDGE_REPLY
        )

    # 馆藏清单：解决"你们馆有什么文物"这类【元问题】。
    # 元问题的答案就是资料目录本身，任何检索都返回不了，只能靠这份清单。
    if catalog:
        system += (
            "\n\n本馆目前收录的资料有：" + "、".join(catalog) + "。"
            "观众问「有什么文物」「有哪些资料」这类问题时，照这个清单回答；"
            "但只能报出名字，不得根据名字编造年代、出土地、尺寸等任何细节。"
        )

    messages = [{"role": "system", "content": system}]
    # 窗口截取已由 memory 按"轮"对齐完成，这里不再二次截断：
    # 原来那句 history[-10:] 会把一轮问答从中间切开，让模型看到没有提问的回答。
    messages += history
    messages.append({"role": "user", "content": question})
    return messages


def chat_reply(question: str, history: list, sources: list, summary: str = "",
               catalog: list = None) -> tuple:
    """文本回答：问题 + 历史摘要 + 对话历史 + 检索资料 → 讲解员式回答

    参数：
        question：观众本轮原话（不要传指代消解改写过的，模型要看到原话）
        history ：[{"role","content"}]，最近若干轮，已按轮对齐
        sources ：rag.retrieve() 返回的资料片段 [{"title","content"}]
        summary ：更早对话的压缩摘要，空串表示还没有

    返回：(回答文本, 用量字典)。用量来自服务端，用于安全阀和排查。
    """
    # 馆内具体信息 + 没有资料 → 直接回固定话术，不过模型。
    # 提示词拦不住模型编造开放时间/展厅名，这里用确定性规则兜底（见 guard.py）。
    if not sources and guard.is_venue_fact(question):
        return config.NO_KNOWLEDGE_REPLY, {}

    data = _chat_raw(_build_messages(question, history, sources, summary, catalog))
    return _content(data), _usage(data)


def stream_reply(question: str, history: list, sources: list, summary: str = "",
                 catalog: list = None):
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
    # 与 chat_reply 保持同一道兜底：馆内具体信息 + 无资料 → 固定话术
    if not sources and guard.is_venue_fact(question):
        yield ("delta", config.NO_KNOWLEDGE_REPLY)
        yield ("usage", {})
        return

    target = _text_target()
    payload = {"model": target["model"],
               "messages": _build_messages(question, history, sources, summary, catalog),
               "stream": True}
    if target["extra"]:
        payload.update(target["extra"])
    if target["stream_options"]:
        payload["stream_options"] = target["stream_options"]
    resp = requests.post(target["url"].rstrip("/") + "/chat/completions",
                         headers=_headers(target["key"]), json=payload,
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

    data = _chat_raw([{"role": "user", "content": "\n\n".join(parts)}])
    return _content(data)
