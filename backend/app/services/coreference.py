# 【角色 D 负责】指代消解（"它"、"这个"到底指什么）
#
# 观众的第二句往往省略主语："它是什么年代的？""这个在哪个展厅？"
# 这种问句直接拿去做 RAG 检索是搜不到资料的——2~3 字滑窗切出来的全是
# "它是/是什么/什么年"这类虚词片，命中数到不了阈值，于是返回空资料，
# 模型被指示回答"馆内资料暂未收录"。明明上一轮刚讲过，观众会觉得机器人失忆了。
#
# 所以必须在检索之前把它补成完整问句："越王勾践剑是什么年代的？"
#
# 实现分两级：
#   第一级（本文件）：话题焦点 + 规则替换。零 API 成本、微秒级——
#                     语音交互对延迟敏感，这一级要覆盖绝大多数情况。
#   第二级（后续按需）：焦点确实不唯一时，再调模型改写，失败即退回原句。
#
# 核心原则：宁可不改，不要猜错。
# 猜错会把检索带去完全无关的资料，让模型一本正经地答错对象，比不消解更糟。
# 所以凡是有歧义信号，一律原样返回。

from pathlib import Path

from ..core import config

# ———— 话题焦点的来源：上一轮回答引用了哪些资料 ————
# 这是最可靠的信号：sources 直接告诉我们上一轮讲的是哪件文物，
# 比在文本里做实体匹配稳得多。

# ———— 代词表（口语优先，按长度倒序替换）————
# 说明几点取舍：
#   1. 「他/她/牠」必须收进来：语音识别经常把「它」写成同音字「他」或「她」，
#      不处理的话语音提问的消解会整体失效。
#   2. 不收「此」「该」：它们更常出现在「因此」「应该」「不该」里，
#      误伤概率远高于收益，而且口语提问基本不会用。
#   3. 复数形式（它们/这些/那些）单独处理，见 PLURAL_PRONOUNS。
_RAW_PRONOUNS = (
    "刚才说的", "上面提到的", "刚刚说的",
    "这件文物", "那件文物", "这个东西", "那个东西",
    "这个", "那个", "这件", "那件", "这只", "那只", "这把", "那把", "这幅", "那幅",
    "它", "他", "她", "牠",
)
PRONOUNS = tuple(sorted(_RAW_PRONOUNS, key=len, reverse=True))

# 复数/集合代词：指向多个对象，替换成单件文物必然出错 → 视为歧义
PLURAL_PRONOUNS = ("它们", "他们", "她们", "这些", "那些")

# 受保护词：字形里含代词，但语义不是回指，替换会破坏原意（"其他"→"其越王勾践剑"）
PROTECTED_WORDS = ("其他", "其它", "他人", "他乡", "他日", "他国")

# 多实体信号：出现这些词往往在比较/并列多件文物 → 不改写
# 刻意收得很窄：「哪些」「都」这类词在单实体问句里也很常见
# （"它有哪些特点""它都有什么故事"），拿来当歧义信号会误杀正常问句。
AMBIGUITY_MARKERS = ("分别", "各自", "两个", "几件", "哪个更", "哪个比较")

# 知识库示例文件的演示前缀（正式资料按 knowledge_base/README.md 的规范直接写文物名）
_DEMO_PREFIXES = ("示例_", "示例-", "demo_", "sample_")

_MASK_START = "\ue000"
_MASK_END = "\ue001"


# ======== 实体识别 ========

def _entity_from_stem(stem: str) -> str:
    """文件名 → 实体名："示例_越王勾践剑" → "越王勾践剑" """
    for prefix in _DEMO_PREFIXES:
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return stem.strip("_- ")


def normalize_title(title: str) -> str:
    """资料标题（rag 返回的 path.stem）→ 实体名，供 sources 做焦点推断"""
    return _entity_from_stem(title)


def known_entities() -> list:
    """知识库里的实体名清单（取文件名）。

    不做缓存：知识库目录很小，一次 glob 约 1ms，而缓存会在角色 C
    新增资料后失效，反倒容易埋坑。
    """
    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    if not kb_dir.exists():
        return []
    names = []
    for path in sorted(kb_dir.glob("**/*")):
        if path.suffix.lower() not in (".md", ".txt") or path.name.upper() == "README.MD":
            continue
        name = _entity_from_stem(path.stem)
        if len(name) >= 2:          # 单字文件名当作噪音
            names.append(name)
    # 长名排前面，保证"越王勾践剑"整体优先于潜在的短名
    return sorted(set(names), key=len, reverse=True)


def find_entities(text: str, entities: list | None = None) -> list:
    """找出文本里出现过的知识库实体，按在文本中的位置排序（去重叠）"""
    if not text:
        return []
    entities = known_entities() if entities is None else entities
    hits = []
    for name in entities:
        idx = text.find(name)
        if idx >= 0:
            hits.append((idx, name))
    hits.sort()

    found = []
    for _, name in hits:
        # 位置靠前的长实体已经覆盖了这段文本，短的就不重复计入
        # （"越王勾践剑"命中后，"勾践剑"不再算第二个实体）
        if not any(name in kept for kept in found):
            found.append(name)
    return found


# ======== 代词检测 ========

def _strip_protected(text: str) -> str:
    """去掉受保护词，避免"其他展厅怎么走"被当成含代词"""
    for word in PROTECTED_WORDS:
        text = text.replace(word, "")
    return text


def _find_pronoun(text: str) -> str:
    """返回文本中第一个（最长的）代词，没有则返回空串"""
    for pronoun in PRONOUNS:
        if pronoun in text:
            return pronoun
    return ""


def has_plural_pronoun(text: str) -> bool:
    return any(p in text for p in PLURAL_PRONOUNS)


def needs_resolution(question: str) -> bool:
    """问句里是否含需要消解的代词"""
    return bool(_find_pronoun(_strip_protected(question or "")))


# ======== 焦点推断 ========

def infer_focus(history: list | None, sources: list | None = None,
                entities: list | None = None) -> tuple:
    """推断当前话题焦点，返回 (焦点实体, 是否歧义)。

    优先看 sources（上一轮回答引用了哪份资料）——这是最可靠的信号。
    拿不到时退回文本匹配：从最近一条消息往前找，哪条提到了知识库实体就用它。
    """
    # 1. 优先用 sources：它直接记录了上一轮实际讲了哪件文物
    if sources:
        names = {normalize_title(t) for t in sources if t}
        names.discard("")
        if len(names) == 1:
            return next(iter(names)), False
        if len(names) > 1:
            return "", True          # 上一轮引了多份资料，指代不明，不猜

    # 2. 退回文本匹配
    entities = known_entities() if entities is None else entities
    for msg in reversed(history or []):
        found = find_entities(msg.get("content", ""), entities)
        if len(found) == 1:
            return found[0], False
        if len(found) > 1:
            return "", True          # 一句话里提到多件文物，可能在比较，不猜
    return "", False


# ======== 改写 ========

def _mask_protected(text: str) -> tuple:
    """把受保护词换成私有区占位符，替换完再还原。

    直接删掉不行（会改变句子结构），不处理又会被"他"的替换破坏。
    """
    restore = {}
    for i, word in enumerate(PROTECTED_WORDS):
        if word in text:
            token = f"{_MASK_START}{i}{_MASK_END}"
            restore[token] = word
            text = text.replace(word, token)
    return text, restore


def _replace_pronouns(question: str, focus: str) -> tuple:
    """把问句里的代词替换成焦点实体，返回 (新问句, 是否发生替换)"""
    text, restore = _mask_protected(question)
    changed = False
    for pronoun in PRONOUNS:        # PRONOUNS 已按长度倒序，长词优先
        if pronoun in text:
            text = text.replace(pronoun, focus)
            changed = True
    for token, word in restore.items():
        text = text.replace(token, word)
    return text, changed


def resolve(question: str, history: list | None = None, sources: list | None = None,
            focus: str = "", entities: list | None = None) -> tuple:
    """把问句里的代词替换成上文明确的对象。

    参数：
        question：用户本轮原话（不要传改写过的，会越改越乱）
        history ：[{"role","content"}] 对话历史
        sources ：上一轮回答引用的资料标题，最可靠的焦点信号
        focus   ：调用方已经确定的焦点，传了就不再看 history/sources
        entities：知识库实体清单，测试时可注入固定值

    返回：(改写后的问句, 说明信息)

    说明信息字段：
        changed    是否发生了改写
        antecedent 采用的焦点实体
        method     rule（规则改写）/ none（未改写）
        reason     未改写的原因，便于排查
    """
    info = {"changed": False, "antecedent": "", "method": "none", "reason": ""}
    question = question or ""

    # 1. 没有代词就不用管
    if not needs_resolution(question):
        info["reason"] = "no_pronoun"
        return question, info

    # 2. 复数代词（它们/这些）指向多个对象，替换成单件必然出错
    if has_plural_pronoun(question):
        info["reason"] = "plural_pronoun"
        return question, info

    # 3. 出现比较/并列信号，多半在问多件文物
    if any(marker in question for marker in AMBIGUITY_MARKERS):
        info["reason"] = "ambiguous"
        return question, info

    # 4. 确定焦点
    if focus:
        antecedent, ambiguous = focus, False
    else:
        antecedent, ambiguous = infer_focus(history, sources, entities)
    info["antecedent"] = antecedent

    if ambiguous:
        info["reason"] = "ambiguous_focus"
        return question, info
    if not antecedent:
        # 会话第一句就说"它"，没有上文可依据——不猜，让模型自己看着办
        info["reason"] = "no_focus"
        return question, info

    # 5. 问句里本来就点到对象了，不需要再补（避免"越王勾践剑它是什么"被改成重复）
    if antecedent in question:
        info["reason"] = "already_grounded"
        return question, info

    # 6. 替换
    rewritten, changed = _replace_pronouns(question, antecedent)
    if changed:
        info.update(changed=True, method="rule", reason="rewritten")
        return rewritten, info

    info["reason"] = "no_pronoun"
    return question, info
