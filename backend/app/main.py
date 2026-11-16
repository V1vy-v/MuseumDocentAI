# 【角色 D 负责】后端服务入口
#
# 启动方式（在 backend/ 目录下）：
#   pip install -r requirements.txt
#   uvicorn app.main:app --reload --port 8000
#
# 对外提供的接口：
#   POST   /api/chat                            文本问答
#   POST   /api/voice                           语音问答（录音进 → 回答+语音出）
#   POST   /api/sessions                        新建会话
#   GET    /api/sessions                        列出历史会话（界面左侧列表用）
#   GET    /api/sessions/{session_id}/messages  拉取历史（APP 重启后回填界面）
#   DELETE /api/sessions/{session_id}           清除会话
#   GET    /api/health                          健康检查（联调时先打这个确认服务活着）
#
# 启动时会自动建好会话数据库（backend/data/chat.db），并清理超过 TTL 未活动的旧会话。
#
# 自测入口：
#   http://127.0.0.1:8000/docs    接口文档（能逐个调接口）
#   http://127.0.0.1:8000/debug   调试台（连续多轮对话，能看消解结果/摘要/token）
#
# 调试台的页面文件在 backend/static/debug.html，纯静态、零构建、无外部依赖。

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import chat, kb, sessions, voice
from .core import config
from .services import llm_client, store, vector_store

DEBUG_PAGE = Path(__file__).resolve().parents[1] / "static" / "debug.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时做两件事：建表、清理过期会话。

    用 lifespan 而不是已被废弃的 @app.on_event("startup")。
    """
    store.init_db()
    removed = store.purge_expired()
    if removed:
        print(f"[启动] 已清理 {removed} 个超过 {config.SESSION_TTL_DAYS} 天未活动的会话")

    # 建/更新向量索引。失败只是降级成关键词检索，不能让服务起不来。
    # 注意：zvec 是进程内数据库，同一个索引目录只能被一个进程打开，
    # 所以必须以单 worker 运行（uvicorn 默认就是 1，别加 --workers）。
    vector_store.ensure_ready()

    print(f"[启动] 文本模型 {llm_client.describe_provider()}")
    print("[启动] 接口文档 http://127.0.0.1:{}/docs   调试台 http://127.0.0.1:{}/debug"
          .format(config.PORT, config.PORT))
    yield


app = FastAPI(title="博物馆导览问答机器人 后端", lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def flatten_http_error(request: Request, exc: StarletteHTTPException):
    """把错误体摊平成前端约定的 {"error", "hint"} 格式。

    背景：FastAPI 的 HTTPException(detail={...}) 会自动再包一层 detail，
    实际返回 {"detail": {"error": "...", "hint": "..."}}；
    但前端 ApiClient.handleResponse 是按平铺解析的（json.has("error")），
    schemas/chat.py 的 ErrorResponse 也声明成平铺——三方不一致，错的是后端。

    不摊平的后果：模型调用失败返回 502 时，前端判定为"成功但 answer 为空"，
    界面上出现一个空气泡，而不是"AI 服务暂时不可用，请稍后再试"。
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = detail                    # 已经是约定格式，直接摊平
    else:
        content = {"detail": detail}        # 其它情况保持 FastAPI 默认形状
    return JSONResponse(status_code=exc.status_code, content=content,
                        headers=getattr(exc, "headers", None))

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(sessions.router)
app.include_router(kb.router)


@app.get("/api/health")
def health():
    """健康检查。顺带回报向量索引状态，方便启动后确认检索是"向量模式"还是"关键词降级"。"""
    return {"status": "ok", "index": vector_store.stats()}


@app.get("/debug", include_in_schema=False)
def debug_page():
    """调试台页面：连续多轮对话，能看到指代消解结果、滚动摘要、token 用量。

    纯静态单文件（backend/static/debug.html），零构建、无外部依赖。
    页面与接口同源，所以不需要配 CORS。
    不放进 OpenAPI schema（/docs）里——它是工具，不是对外接口。
    """
    if not DEBUG_PAGE.exists():
        raise HTTPException(status_code=404,
                            detail={"error": "debug page not found",
                                    "hint": "缺少文件 backend/static/debug.html"})
    return FileResponse(DEBUG_PAGE)
