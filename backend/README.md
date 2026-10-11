# 后端：博物馆导览问答服务（角色 C、D 的主战场）

技术栈：Python + FastAPI（轻量的 Web 服务框架，浏览器/APP 都能调用）

## 怎么跑起来

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

跑起来后，浏览器打开 `http://127.0.0.1:8000/docs` 能看到自动生成的接口文档。

## 目录说明

| 位置 | 谁负责 | 放什么 |
|---|---|---|
| `app/main.py` | D | 服务入口，启动后先访问 `/docs` 自测 |
| `app/api/` | D | 对外接口：`chat.py` 文本问答、`voice.py` 语音问答 |
| `app/services/llm_client.py` | D | 封装 mimo-v2.5-asr 的调用（语音输入→回答） |
| `app/services/tts_client.py` | D | 语音合成（mimo 无语音输出时启用） |
| `app/services/rag.py` | C | 检索增强：查询改写、检索资料、防幻觉、给出来源 |
| `app/services/memory.py` | D | 多轮对话记忆：历史保存、指代消解（"它"指什么） |
| `app/core/config.py` | D | 配置：模型名、API 密钥（**不要把密钥提交到仓库**） |
| `app/schemas/chat.py` | D | 请求/响应格式约定 |
| `knowledge_base/` | C | 博物馆资料（文物介绍、历史背景、展厅路线、书画知识）+ 向量库 |

## 配置说明

模型相关的所有配置集中在 `app/core/config.py`。
API 密钥建议放到环境变量或本地私密文件里（该文件已在 `.gitignore` 范围内，勿提交）。
