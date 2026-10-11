# 【角色 D 负责】错误响应格式测试
#
# 运行（在 backend/ 目录下）：
#   .venv\Scripts\python.exe -m unittest discover -s tests -t .
#
# 这个格式是跨端契约：前端 ApiClient.handleResponse 用 json.has("error") 判断出错，
# schemas/chat.py 的 ErrorResponse 也声明成平铺。而 FastAPI 的
# HTTPException(detail={...}) 默认会包一层 detail，导致三者不一致——
# 模型调用失败时前端会显示空气泡而不是友好提示。main.py 里的异常处理器负责摊平。

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException                      # noqa: E402

from app.core import config                            # noqa: E402
from app.services import store                         # noqa: E402


def _handle(exc):
    """直接调用异常处理器，避免依赖 httpx / TestClient"""
    from app.main import flatten_http_error
    return asyncio.run(flatten_http_error(None, exc))


class ErrorFormatTest(unittest.TestCase):

    def test_dict_detail_is_flattened(self):
        resp = _handle(HTTPException(status_code=502,
                                     detail={"error": "boom", "hint": "AI 服务暂时不可用"}))
        self.assertEqual(resp.status_code, 502)
        body = json.loads(resp.body)
        self.assertEqual(body, {"error": "boom", "hint": "AI 服务暂时不可用"})
        self.assertNotIn("detail", body, "不能再套一层 detail，前端只读一层")

    def test_plain_detail_keeps_default_shape(self):
        """非约定格式的 detail 保持 FastAPI 默认形状，不要瞎改"""
        resp = _handle(HTTPException(status_code=404, detail="Not Found"))
        self.assertEqual(json.loads(resp.body), {"detail": "Not Found"})

    def test_status_code_preserved(self):
        for code in (400, 404, 502):
            with self.subTest(code=code):
                resp = _handle(HTTPException(status_code=code, detail={"error": "x", "hint": "y"}))
                self.assertEqual(resp.status_code, code)


class RealEndpointErrorShapeTest(unittest.TestCase):
    """真实接口抛出的错误，摊平后也必须带 hint（前端靠它给用户提示）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db, self._orig_data = config.DB_PATH, config.DATA_DIR
        config.DATA_DIR = Path(self._tmp.name)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        store._schema_ready = False
        store.init_db()

    def tearDown(self):
        config.DB_PATH, config.DATA_DIR = self._orig_db, self._orig_data
        store._schema_ready = False
        self._tmp.cleanup()

    def test_missing_session_error_is_flat(self):
        from app.api.sessions import get_messages
        with self.assertRaises(HTTPException) as ctx:
            get_messages("never-existed")
        body = json.loads(_handle(ctx.exception).body)
        self.assertEqual(set(body.keys()), {"error", "hint"})
        self.assertTrue(body["hint"], "hint 是给用户看的，不能为空")


if __name__ == "__main__":
    unittest.main(verbosity=2)
