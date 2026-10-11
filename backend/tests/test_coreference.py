# 【角色 D 负责】指代消解单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 说明：本项目 venv 里没有 pip/pytest，所以用标准库 unittest——零依赖才真跑得起来。
# pytest 原生支持 unittest.TestCase，将来装了 pytest 可直接跑这些用例。

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import coreference  # noqa: E402

# 测试用固定实体表，避免依赖知识库当前内容（角色 C 会随时增删资料）
ENTITIES = ["越王勾践剑", "曾侯乙编钟", "青铜展厅路线"]


class PronounDetectionTest(unittest.TestCase):
    """第 1 步：判断问句是否需要消解"""

    def test_detects_common_pronouns(self):
        for q in ["它是什么年代的？", "这个在哪个展厅？", "那件文物值钱吗？",
                  "这件文物有什么特点？", "刚才说的那个在哪？"]:
            with self.subTest(q=q):
                self.assertTrue(coreference.needs_resolution(q), q)

    def test_detects_asr_homophones(self):
        """语音识别常把"它"写成同音字，漏掉的话语音场景消解会整体失效"""
        for q in ["他是什么年代的？", "她出土于哪里？", "牠在哪个展厅？"]:
            with self.subTest(q=q):
                self.assertTrue(coreference.needs_resolution(q), q)

    def test_plain_question_needs_no_resolution(self):
        self.assertFalse(coreference.needs_resolution("越王勾践剑是什么时期的文物？"))
        self.assertFalse(coreference.needs_resolution("博物馆今天开放吗？"))

    def test_other_is_not_a_pronoun(self):
        """「其他」含"他"字，但语义不是回指，误判会导致"其越王勾践剑"这种错乱"""
        self.assertFalse(coreference.needs_resolution("其他展厅怎么走？"))
        self.assertFalse(coreference.needs_resolution("还有其它问题吗？"))

    def test_formal_words_are_not_pronouns(self):
        """刻意不收「该」「此」：在"应该""因此"里误伤率远高于收益"""
        self.assertFalse(coreference.needs_resolution("应该往哪走？"))
        self.assertFalse(coreference.needs_resolution("因此要预约吗？"))


class FocusInferenceTest(unittest.TestCase):
    """第 2 步：推断"它"指的是谁"""

    def test_focus_from_sources(self):
        focus, ambiguous = coreference.infer_focus([], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(focus, "越王勾践剑")
        self.assertFalse(ambiguous)

    def test_sources_win_over_history(self):
        """sources 记录的是上一轮实际引用的资料，比文本匹配可靠"""
        history = [{"role": "user", "content": "曾侯乙编钟是什么？"}]
        focus, _ = coreference.infer_focus(history, sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(focus, "越王勾践剑")

    def test_focus_from_history_text_when_no_sources(self):
        history = [
            {"role": "user", "content": "越王勾践剑是什么时期的文物？"},
            {"role": "assistant", "content": "越王勾践剑是春秋晚期越国青铜剑，现藏于湖北省博物馆。"},
        ]
        focus, ambiguous = coreference.infer_focus(history, sources=None, entities=ENTITIES)
        self.assertEqual(focus, "越王勾践剑")
        self.assertFalse(ambiguous)

    def test_multiple_sources_is_ambiguous(self):
        focus, ambiguous = coreference.infer_focus(
            [], sources=["示例_越王勾践剑", "曾侯乙编钟"], entities=ENTITIES)
        self.assertTrue(ambiguous, "上一轮引了多份资料，指代不明，不能瞎猜")
        self.assertEqual(focus, "")

    def test_multiple_entities_in_one_message_is_ambiguous(self):
        history = [{"role": "user", "content": "越王勾践剑和曾侯乙编钟哪个早？"}]
        _, ambiguous = coreference.infer_focus(history, sources=None, entities=ENTITIES)
        self.assertTrue(ambiguous)

    def test_no_focus_in_empty_history(self):
        focus, ambiguous = coreference.infer_focus([], sources=None, entities=ENTITIES)
        self.assertEqual(focus, "")
        self.assertFalse(ambiguous)

    def test_nested_entity_not_double_counted(self):
        """"越王勾践剑"命中后，不该再把"勾践剑"算成第二个实体（否则会误判歧义）"""
        found = coreference.find_entities("越王勾践剑", entities=["越王勾践剑", "勾践剑"])
        self.assertEqual(found, ["越王勾践剑"])


class ResolveTest(unittest.TestCase):
    """第 3 步：改写问句"""

    def test_rewrites_pronoun_from_sources(self):
        resolved, info = coreference.resolve(
            "它是什么年代的？", [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, "越王勾践剑是什么年代的？")
        self.assertTrue(info["changed"])
        self.assertEqual(info["method"], "rule")
        self.assertEqual(info["antecedent"], "越王勾践剑")

    def test_rewrites_asr_homophone(self):
        resolved, info = coreference.resolve(
            "他是什么年代的？", [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, "越王勾践剑是什么年代的？")
        self.assertTrue(info["changed"])

    def test_rewrites_long_pronoun(self):
        resolved, _ = coreference.resolve(
            "这件文物在哪个展厅？", [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, "越王勾践剑在哪个展厅？")

    def test_rewrites_from_history_without_sources(self):
        history = [{"role": "user", "content": "越王勾践剑是什么时期的文物？"}]
        resolved, info = coreference.resolve(
            "它是什么年代的？", history, sources=None, entities=ENTITIES)
        self.assertEqual(resolved, "越王勾践剑是什么年代的？")

    def test_no_focus_keeps_question(self):
        """会话第一句就说"它"，没有上文可依据 → 不猜"""
        q = "它是什么年代的？"
        resolved, info = coreference.resolve(q, [], sources=None, entities=ENTITIES)
        self.assertEqual(resolved, q)
        self.assertFalse(info["changed"])
        self.assertEqual(info["reason"], "no_focus")

    def test_plural_pronoun_keeps_question(self):
        q = "它们都是什么年代的？"
        resolved, info = coreference.resolve(q, [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, q)
        self.assertEqual(info["reason"], "plural_pronoun")

    def test_ambiguous_sources_keep_question(self):
        q = "它是什么年代的？"
        resolved, info = coreference.resolve(
            q, [], sources=["示例_越王勾践剑", "曾侯乙编钟"], entities=ENTITIES)
        self.assertEqual(resolved, q)
        self.assertEqual(info["reason"], "ambiguous_focus")

    def test_comparison_marker_keeps_question(self):
        q = "它们两个分别是什么年代的？"
        _, info = coreference.resolve(q, [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertIn(info["reason"], ("plural_pronoun", "ambiguous"))

    def test_already_grounded_keeps_question(self):
        """问句里本来就点了对象，别再补一遍变成"越王勾践剑越王勾践剑是…\""""
        q = "越王勾践剑它是哪个年代的？"
        resolved, info = coreference.resolve(q, [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, q)
        self.assertEqual(info["reason"], "already_grounded")

    def test_protected_word_survives_replacement(self):
        """"其他"不能被"他"的替换破坏"""
        resolved, info = coreference.resolve(
            "其他展厅和它有什么关系？", [], sources=["示例_越王勾践剑"], entities=ENTITIES)
        self.assertEqual(resolved, "其他展厅和越王勾践剑有什么关系？")
        self.assertTrue(info["changed"])

    def test_no_pronoun_returns_reason(self):
        q = "越王勾践剑是什么时期的文物？"
        resolved, info = coreference.resolve(q, [], entities=ENTITIES)
        self.assertEqual(resolved, q)
        self.assertEqual(info["reason"], "no_pronoun")

    def test_explicit_focus_argument(self):
        resolved, _ = coreference.resolve("它在哪？", [], focus="曾侯乙编钟", entities=ENTITIES)
        self.assertEqual(resolved, "曾侯乙编钟在哪？")


class KnownEntitiesTest(unittest.TestCase):
    """实体清单取自知识库文件名"""

    def test_reads_knowledge_base_and_strips_demo_prefix(self):
        names = coreference.known_entities()
        self.assertIn("越王勾践剑", names)
        self.assertNotIn("示例_越王勾践剑", names, "演示前缀应被去掉")
        self.assertFalse([n for n in names if "README" in n.upper()], "README 不该当实体")

    def test_normalize_title(self):
        self.assertEqual(coreference.normalize_title("示例_越王勾践剑"), "越王勾践剑")
        self.assertEqual(coreference.normalize_title("越王勾践剑"), "越王勾践剑")


if __name__ == "__main__":
    unittest.main(verbosity=2)
