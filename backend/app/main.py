# 【角色 D 负责】后端服务入口
#
# 启动方式（在 backend/ 目录下）：
#   pip install -r requirements.txt
#   uvicorn app.main:app --reload --port 8000
#
# 对外提供的接口：
#   POST /api/chat   文本问答
#   POST /api/voice  语音问答（录音进 → 回答+语音出）
#   GET  /api/health 健康检查（联调时先打这个确认服务活着）
#
# 自测方法：服务跑起来后打开 http://127.0.0.1:8000/docs

from fastapi import FastAPI

from .api import chat, voice

app = FastAPI(title="博物馆导览问答机器人 后端")

app.include_router(chat.router)
app.include_router(voice.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
