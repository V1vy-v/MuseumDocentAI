# 【角色 D 负责】句子级语音合成流水线
#
# 解决什么问题：回答是流式返回的，文字一两秒就出来了，但语音要等
# 「整段生成完 → 整段合成」才开始，观众会干等五秒以上。
#
# 这里的做法：文本一边流进来，一边按句切分、送进后台线程合成；
# 每合成好一句就交出去，客户端可以立即播这一句，不用等全文。
#
# 为什么这样不会断档（实测数据支撑）：
#   TTS 耗时 ≈ 0.7s + 35ms/字；播放速度约 250ms/字。
#   合成比播放快约 4 倍，所以只要第一句出来了，后面的句子在播放期间
#   一定合成得完，队列只会越攒越多，不会出现"播完了还没合成好"。
#
# 三个必须守住的边界：
#   1. 单句合成失败只跳过这句，不能让整条语音链断掉，更不能影响文字回答；
#   2. 整轮有字数上限（模型偶尔会输出很长），否则 TTS 额度会被吃光；
#   3. 客户端中途断开时必须能立刻停掉后台线程，不能泄漏。

import queue
import re
import threading
import time

from . import tts_client

# 句末标点：句号/问号/感叹号/分号 + 换行。
# 逗号不在其中 —— 在逗号处切开会把一句话拆碎，听起来一顿一顿的。
_SENTENCE_END = re.compile(r"[。！？!?；;\n]")

# 太短的片段不值得单独合成一次（固定开销约 0.7 秒），攒够再送。
_MIN_CHARS = 8
# 单句上限：没有标点的长段落也要切，否则第一句永远等不到。
_MAX_CHARS = 40
# 整轮最多合成多少字。600 字约 21 秒语音，足够一次完整讲解。
_MAX_TOTAL = 600

_STOP = object()        # 队列哨兵：收到它就退出，不再合成

# 第一段可以短一点：句号往往要等模型写完一整句（20~40 字），而观众等的是
# "多快听到声音"。所以只在【第一句】允许在逗号处切开；后面的句子仍按句末
# 标点切，避免整段听起来一顿一顿。
_CLAUSE_END = re.compile(r"[，,、：:]")
_MIN_FIRST = 10          # 第一段最短 10 字，太短气口不自然


def _first_clause(text: str) -> tuple:
    """从累积文本里切出"第一段"（到第一个逗号为止）。

    返回 (第一段文本, 剩余文本)；还没等到逗号、或逗号太靠前时返回 ("", text)。
    """
    for m in _CLAUSE_END.finditer(text):
        if m.end() >= _MIN_FIRST:
            head, rest = text[:m.end()], text[m.end():]
            # 逗号留在上一段会让合成停顿更自然
            return head, rest
    return "", text


def split_sentences(text: str, *, final: bool = False) -> tuple:
    """把累积文本切成 (完整句子列表, 还没说完的尾巴)。

    final=True 表示文本已经结束，尾巴不管有没有标点都当一句收掉。
    """
    sentences = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        piece = text[start:m.end()]
        if piece.strip():
            sentences.append(piece)
        start = m.end()

    rest = text[start:]
    # 超长且没有标点：硬切，保证能尽早发出第一段
    while len(rest) >= _MAX_CHARS:
        sentences.append(rest[:_MAX_CHARS])
        rest = rest[_MAX_CHARS:]

    if final and rest.strip():
        sentences.append(rest)
        rest = ""

    return sentences, rest


class SentenceSpeaker:
    """把流式文本变成"边合成边交出音频"的后台流水线。

    用法：
        sp = SentenceSpeaker(); sp.start()
        sp.feed("越王勾践剑是春秋晚期的。")     # 生成过程中反复调用
        ...
        sp.flush(); sp.close()
        while True:
            items = sp.poll(0.5)                # [(序号, WAV 字节), ...]
            for idx, data in items: ...
            if sp.finished() and not items:
                break

    poll() 返回的序号从 0 递增，客户端应按序播放（多句不能乱序播）。
    """

    def __init__(self) -> None:
        self._inbox: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._out: list = []          # [(index, wav_bytes)]
        self._buf = ""                # 还没凑成完整句子的尾巴
        self._pending = ""            # 太短、等着和下一句拼起来的片段
        self._index = 0
        self._chars = 0               # 已送出合成的字数
        self._error = ""              # 第一次失败的原因（之后不再尝试）
        self._accepting = True        # 还接不接受新文本
        self._abort = threading.Event()      # 客户端断开时置位
        self._finished = threading.Event()   # 后台线程已退出
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ---------- 对外 ----------

    def start(self) -> None:
        self._thread.start()

    def feed(self, delta: str) -> None:
        """喂入一段文本增量，凑出的完整句子立即排队等合成。"""
        if not self._accepting:
            return
        self._buf += delta

        # 还没送出过任何一段时，允许在逗号处切一刀，让第一句更早出声
        if self._index == 0 and not self._pending:
            early, rest = _first_clause(self._buf)
            if early:
                self._buf = rest
                self._emit_text(early)
                return

        ready, self._buf = split_sentences(self._buf)
        self._enqueue(ready)

    def flush(self) -> None:
        """文本结束：把最后没标点的一句也送去合成。"""
        if not self._accepting:
            return
        ready, self._buf = split_sentences(self._buf, final=True)
        self._enqueue(ready)
        if self._pending:
            self._emit_text(self._pending)
            self._pending = ""

    def close(self) -> None:
        """告诉后台线程：不会再有新句子了。"""
        if self._accepting:
            self._accepting = False
            self._inbox.put(_STOP)

    def stop(self) -> None:
        """客户端断开时调用：立刻放弃剩余句子，不等它们合成完。"""
        self._accepting = False
        self._abort.set()
        self._inbox.put(_STOP)       # 即使线程正阻塞在 get() 上也能唤醒

    def poll(self, timeout: float = 0.0) -> list:
        """取出已合成好的音频；timeout>0 时最多等这么久。"""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._out:
                    items, self._out = self._out, []
                    return items
            if self._finished.is_set():
                return []
            if time.time() >= deadline:
                return []
            time.sleep(0.02)

    def finished(self) -> bool:
        """后台线程已经退出（正常收尾或出错）。"""
        return self._finished.is_set()

    @property
    def error(self) -> str:
        return self._error

    @property
    def emitted_chars(self) -> int:
        return self._chars

    # ---------- 内部 ----------

    def _enqueue(self, sentences: list) -> None:
        for s in sentences:
            if self._error or self._abort.is_set():
                return
            self._pending += s
            # 太短的片段攒着，等凑够 _MIN_CHARS 再一次合成，省掉固定开销
            if len(self._pending) < _MIN_CHARS:
                continue
            text, self._pending = self._pending, ""
            self._emit_text(text)

    def _emit_text(self, text: str) -> None:
        if self._chars >= _MAX_TOTAL:
            return
        if self._chars + len(text) > _MAX_TOTAL:
            text = text[:_MAX_TOTAL - self._chars]
        if not text.strip():
            return
        self._chars += len(text)
        self._inbox.put((self._index, text))
        self._index += 1

    def _run(self) -> None:
        try:
            while True:
                item = self._inbox.get()
                if item is _STOP or self._abort.is_set():
                    return
                idx, text = item
                if self._abort.is_set():
                    return
                try:
                    data = tts_client.synthesize(text)
                except tts_client.TTSUnavailable as exc:
                    # 一次失败就不再重试：多半是没配置或额度问题，
                    # 继续重试只会把整条流拖死。文字回答照常给。
                    self._error = str(exc)
                    return
                except Exception as exc:            # noqa: BLE001
                    self._error = f"{type(exc).__name__}: {exc}"
                    return
                with self._lock:
                    # 连文字一起交出去：客户端拿它把"这一句"显示出来，
                    # 文字和语音就同步了（谁先出都不会错位）。
                    self._out.append((idx, text, data))
        finally:
            self._finished.set()
