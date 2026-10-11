# 【角色 D 负责】前后端数据格式约定（占位骨架）
#
# 这里定义"接口收什么、回什么"，前端按这个格式解析，避免两边对不上。
#
# 文本问答 POST /api/chat
#   请求：{ "question": "越王勾践剑在哪里展出？", "session_id": "abc123" }
#   响应：{ "answer": "越王勾践剑在二楼青铜展厅…",
#          "sources": ["青铜器图录 第12页", "展厅手册"] }
#
# 语音问答 POST /api/voice
#   请求：multipart 上传：audio=录音文件, session_id=abc123
#   响应：{ "answer": "…", "sources": [...], "audio_url": "(可选)回答音频地址" }
#
# 错误统一格式：
#   { "error": "错误说明", "hint": "给用户看的友好提示" }
