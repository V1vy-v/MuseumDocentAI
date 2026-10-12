# 【角色 D 负责】配置读取的单元测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config  # noqa: E402


class IntEnvTest(unittest.TestCase):
    """_int_env：数值配置可被环境变量覆盖，非法值退回默认"""

    def test_returns_default_when_absent(self):
        self.assertEqual(config._int_env("MUSEUM_TEST_NOT_SET_ANYWHERE", 42), 42)

    def test_reads_env_value(self):
        with mock.patch.dict(os.environ, {"MUSEUM_TEST_INT": "200"}):
            self.assertEqual(config._int_env("MUSEUM_TEST_INT", 42), 200)

    def test_invalid_value_falls_back_to_default(self):
        """配置写错不该把服务带崩"""
        for bad in ("不是数字", "", "3.5", "abc", "12x"):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {"MUSEUM_TEST_INT": bad}):
                self.assertEqual(config._int_env("MUSEUM_TEST_INT", 42), 42)

    def test_negative_and_zero_are_accepted(self):
        """不在这里做范围校验：0 或负数有测试用途（例如立刻触发压缩）"""
        with mock.patch.dict(os.environ, {"MUSEUM_TEST_INT": "0"}):
            self.assertEqual(config._int_env("MUSEUM_TEST_INT", 42), 0)


class ConfigWiringTest(unittest.TestCase):
    """确认那几个数值项确实走 _int_env，而不是写死的字面量。

    这里用源码检查而不是 reload 模块：reload 会把 config.DB_PATH 一起重算，
    可能把别的用例的临时库隔离搞坏——代价不值得。
    """

    def test_token_budgets_come_from_env_helper(self):
        src = inspect.getsource(config)
        for name in ("RECENT_TOKEN_BUDGET", "SUMMARY_TRIGGER_TOKENS",
                     "SUMMARY_MAX_CHARS", "PROMPT_TOKEN_ALERT"):
            with self.subTest(name=name):
                self.assertIn(f'{name} = _int_env("{name}"', src,
                              f"{name} 没有走 _int_env，环境变量覆盖不会生效")

    def test_defaults_are_sane(self):
        self.assertGreater(config.RECENT_TOKEN_BUDGET, 0)
        self.assertGreater(config.SUMMARY_TRIGGER_TOKENS, 0)
        self.assertGreater(config.PROMPT_TOKEN_ALERT, config.RECENT_TOKEN_BUDGET)


if __name__ == "__main__":
    unittest.main(verbosity=2)
