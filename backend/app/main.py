# 【角色 D 负责】后端服务入口（占位骨架）
#
# 启动方式（在 backend/ 目录下）：
#   pip install -r requirements.txt
#   uvicorn app.main:app --reload --port 8000
#
# 对外提供的接口（实现在 app/api/ 下）：
#   POST /api/chat   文本问答：收到问题，返回回答 + 资料来源
#   POST /api/voice  语音问答：收到录音，直接交给 mimo-v2.5-asr，返回回答
#
# 自测方法：服务跑起来后打开 http://127.0.0.1:8000/docs

from fastapi import FastAPI

app = FastAPI(title="博物馆导览问答机器人 后端")

# TODO(角色D)：把 app/api/ 里的接口挂载到这里
