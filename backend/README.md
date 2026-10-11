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
| `app/services/store.py` | D | 对话持久化仓储层（SQLite）：建表、读写、TTL 清理 |
| `app/services/memory.py` | D | 多轮对话记忆：历史保存、上下文窗口、最近摘要 |
| `app/services/coreference.py` | D | 指代消解：把「它」「这个」补成完整问句（先消解再检索） |
| `app/core/config.py` | D | 配置：模型名、API 密钥、数据库路径（**不要把密钥提交到仓库**） |
| `app/schemas/chat.py` | D | 请求/响应格式约定（**前端接口契约，不要改现有字段**） |
| `knowledge_base/` | C | 博物馆资料（文物介绍、历史背景、展厅路线、书画知识）+ 向量库 |
| `tests/` | D | 单元测试（标准库 unittest，零依赖） |
| `docs/` | D | 后端设计文档；跨前后端的全局文档放仓库根的 `docs/` |
| `data/` | — | 运行时生成的会话数据库（已 gitignore，**不要提交**） |

## 跑测试

```bash
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -t .      # 全部用例
.venv\Scripts\python.exe -m unittest tests.test_coreference      # 单个文件
```

用标准库 `unittest`，不需要装任何东西。想用 pytest 跑同一批用例也行（pytest 原生支持
`unittest.TestCase`）：`uv pip install pytest && pytest tests/`。

联调自测脚本（需要服务已启动、且配置了真实 API 密钥）：

```bash
.venv\Scripts\python.exe scripts\smoke_test.py
```

它会依次验证：服务存活 → 完整问句问答 → **同会话用「它」追问仍能检索到资料** → 语音闭环。
第 3 步是指代消解的回归项。

## 上下文与指代消解的行为说明

- 对话按 `session_id` 存进 SQLite，**服务重启后不丢**。前端不调建会话接口也能用
  （首次写入时自动建会话）。
- 上下文窗口按"轮"对齐（默认最近 6 轮），保证喂给模型的历史以观众提问开头，
  不会出现"只有回答、没有提问"的半截上下文。
- 指代消解遵循**宁可不改、不要猜错**：只有能确定唯一对象时才改写问句，
  遇到复数代词（它们/这些）、比较并列（分别/两个）、或焦点不唯一，一律原样返回。
- 用户原话与消解结果**分列存储**（`content` / `resolved`），展示与摘要始终用原话。


## 配置说明

模型相关的所有配置集中在 `app/core/config.py`。
API 密钥建议放到环境变量或本地私密文件里（该文件已在 `.gitignore` 范围内，勿提交）。
