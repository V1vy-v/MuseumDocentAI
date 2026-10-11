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
#   GET    /api/sessions/{session_id}/messages  拉取历史（APP 重启后回填界面）
#   DELETE /api/sessions/{session_id}           清除会话
#   GET    /api/health                          健康检查（联调时先打这个确认服务活着）
#
# 启动时会自动建好会话数据库（backend/data/chat.db），并清理超过 TTL 未活动的旧会话。
#
# 自测方法：服务跑起来后打开 http://127.0.0.1:8000/docs

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import chat, sessions, voice
from .core import config
from .services import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时做两件事：建表、清理过期会话。

    用 lifespan 而不是已被废弃的 @app.on_event("startup")。
    """
    store.init_db()
    removed = store.purge_expired()
    if removed:
        print(f"[启动] 已清理 {removed} 个超过 {config.SESSION_TTL_DAYS} 天未活动的会话")
    yield


app = FastAPI(title="博物馆导览问答机器人 后端", lifespan=lifespan)

app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(sessions.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
