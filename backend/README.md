# 后端：博物馆导览问答服务（角色 C、D 的主战场）

技术栈：Python + FastAPI（轻量的 Web 服务框架，浏览器/APP 都能调用）

## 怎么跑起来

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

跑起来后浏览器打开：

- `http://127.0.0.1:8000/docs` —— 自动生成的接口文档，能逐个调接口
- `http://127.0.0.1:8000/debug` —— **调试台**，用来调这一步的记忆/会话功能

### 调试台能看什么

`/docs` 只能一个一个调接口，看不到"跨轮"的东西。调试台补上这些：

- **指代消解结果**：每条观众提问下面标出 `它` / `这个` 被改写成了什么
- **滚动摘要**：长对话压缩出来的那段摘要原文
- **token 明细**：每条消息的 token 估算值 + 最近一次请求的真实 `prompt_tokens`
  （上下文窗口就是按这些算的，出问题时一眼能看出窗口是怎么切的）
- **会话管理**：新建 / 载入历史 / 删除，含"删除是幂等的"这类行为验证
- **左侧历史会话列表**：像通用聊天应用那样列出所有对话（标题取首问、相对时间、
  消息条数），点一下切换，悬停出删除按钮。空会话（没发过消息的）默认不显示
- **一键跑指代消解回归**：依次发三句，验证「它」「这个」都能正确指向
- **流式输出开关**：勾上走 `/api/chat/stream`，边生成边显示，并在气泡下标出
  **首字延迟 / 总耗时 / 分块数**；取消勾选走 `/api/chat`，可以直接对比两种体感
- **原始报文**：最近一次请求与响应，出错时能直接看到后端的 `{error, hint}`

页面就是单个静态文件 `static/debug.html`，纯原生 JS，**零构建、无外部依赖、离线可用**。
改完直接刷新浏览器即可，不用重启服务。它本身不是对外接口，所以没进 `/docs`。

### 临时调参（比如想立刻看到滚动摘要）

这几个数值配置可以用环境变量覆盖，**不用改代码**：

```powershell
# PowerShell：把窗口和阈值都压到很小，聊几轮就能看到摘要
$env:RECENT_TOKEN_BUDGET = "200"
$env:SUMMARY_TRIGGER_TOKENS = "150"
uvicorn app.main:app --reload --port 8000
```

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `CHAT_DB_PATH` | `backend/data/chat.db` | 数据库位置（测试用它指到临时文件） |
| `RECENT_TOKEN_BUDGET` | 12000 | 最近多少 token 的对话原样喂给模型（约 160 轮） |
| `SUMMARY_TRIGGER_TOKENS` | 1500 | 滑出窗口的部分累积超过此值才压缩一次 |
| `SUMMARY_MAX_CHARS` | 400 | 摘要长度上限 |
| `PROMPT_TOKEN_ALERT` | 200000 | 提示词超过此值就告警 |

值写错（比如填了非数字）会退回默认值，不会把服务带崩。

## 目录说明

| 位置 | 谁负责 | 放什么 |
|---|---|---|
| `app/main.py` | D | 服务入口；启动时建表、清理过期会话、建/更新向量索引（lifespan） |
| `app/api/` | D | 对外接口：`chat.py` 文本问答、`voice.py` 语音问答、`sessions.py` 会话管理、`kb.py` 资料原文浏览 |
| `app/services/llm_client.py` | D | 封装 DeepSeek 的调用（文本问答 / 流式 / 摘要 / 语音识别） |
| `app/services/tts_client.py` | D | 语音合成（当前无可用服务，未配置时只返回文字） |
| `app/services/rag.py` | C | 检索门面：选路、融合、防幻觉、给出来源与原文链接 |
| `app/services/vector_store.py` | C | zvec 向量库：建库、增量同步、向量距离闸门 + BM25 混合检索 |
| `app/services/chunker.py` | C | 把资料按 Markdown 结构切成检索单元 |
| `app/services/embeddings.py` | C | 文本向量化（火山 Ark doubao-embedding-vision） |
| `app/services/guard.py` | D | 本馆信息类问题识别：没资料时直接回固定话术，不给模型编造的机会 |
| `app/services/store.py` | D | 对话持久化仓储层（SQLite）：建表、读写、TTL 清理 |
| `app/services/memory.py` | D | 多轮对话记忆：历史保存、上下文窗口、最近摘要 |
| `app/services/coreference.py` | D | 指代消解：把「它」「这个」补成完整问句（先消解再检索） |
| `app/core/config.py` | D | 配置：模型名、API 密钥、检索阈值、数据库路径（**不要把密钥提交到仓库**） |
| `app/schemas/chat.py` | D | 请求/响应格式约定（**前端接口契约，不要改现有字段**） |
| `app/schemas/session.py` | D | 会话管理接口的数据格式 |
| `knowledge_base/` | C | 博物馆资料（文物介绍、历史背景、展厅路线、书画知识），启动时自动建向量索引 |
| `static/debug.html` | D | 调试台页面（纯静态单文件，挂在 `/debug`） |
| `tests/` | D | 单元测试（标准库 unittest，零依赖） |
| `docs/` | D | 后端文档：`后端PRD.md`（需求文档，课程用）、`接口文档.md`、`记忆系统与指代消解方案.md`；跨前后端的全局文档放仓库根的 `docs/` |
| `data/` | — | 运行时生成的会话数据库（已 gitignore，**不要提交**） |

## 接口清单

| 接口 | 说明 | 前端要不要调 |
|---|---|---|
| `POST /api/chat` | 文本问答 `{question, session_id}` → `{answer, sources}` | 已在用 |
| `POST /api/chat/stream` | **流式问答（SSE）**：`meta` → `delta`* → `done`/`error` | **可选**（接了才有打字机效果） |
| `POST /api/voice` | 语音问答（multipart：`audio` + `session_id`）→ `{question, answer, sources, audio_base64}` | 已在用 |
| `GET /api/health` | 健康检查（附带向量索引状态：就绪 / 关键词降级） | 联调用 |
| `GET /api/kb/{路径}` | 资料原文（`sources` 对应的 Markdown 渲染页，只读） | 不用调（调试台点来源气泡时用） |
| `POST /api/sessions` | 新建会话 → `{session_id, created_at, existed}` | **可选** |
| `GET /api/sessions` | 历史会话列表 → `{sessions: [...], count}` | **可选** |
| `GET /api/sessions/{id}/messages` | 拉取历史 → `{session_id, title, summary, messages[]}` | **可选** |
| `DELETE /api/sessions/{id}` | 清除会话（幂等，不存在返回 `deleted:false`） | **可选** |

**关键：`/api/chat` 和 `/api/voice` 的入参和回参都没有变**，前端 `ApiClient` 一行都不用改。

会话管理这四个是**可选增强**：`/api/chat`、`/api/voice` 首次写入时会自动建会话，
所以前端照旧自己生成 UUID、完全不调它们，问答和持久化也正常工作。
只有当你想实现「重启 APP 后恢复上次对话」时才需要用到：

1. 把 `session_id` 存进 `SharedPreferences`（替代现在的每次 `UUID.randomUUID()`）；
2. 启动时调 `GET /api/sessions/{id}/messages` 把历史回填到对话列表。

`/docs` 里有可直接调用的交互式文档。

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

它会依次验证：服务存活 → 完整问句问答 → **同会话用「它」追问仍能检索到资料** → 语音接口。
第 3 步是指代消解的回归项。

## 上下文与指代消解的行为说明

- 对话按 `session_id` 存进 SQLite，**服务重启后不丢**。前端不调建会话接口也能用
  （首次写入时自动建会话）。
- 上下文窗口**按 token 预算取**（`RECENT_TOKEN_BUDGET = 12000`，约 160 轮），不是按消息条数——
  一条 500 字的资料和一句"嗯"都算一条消息，按条数切完全不准。
  窗口边界按"轮"对齐：以观众提问开头，不会出现"只有回答、没有提问"的半截上下文。
  预算装下奇数条时是**往前补提问**，不是砍掉回答（否则会丢掉半轮）。
  > 窗口敢开到 12000 是有实测依据的：模型上下文 1M、输入 $0.14/1M token
  > （12000 token ≈ $0.0017/次），且实测提示词从 162 token 拉到 23598 token
  > **耗时没有变差**，前缀缓存也生效。所以限制窗口的不是"装不下"。
- **长对话滚动摘要**：滑出窗口、且还没被压缩的旧对话累积超过
  `SUMMARY_TRIGGER_TOKENS = 1500` 时压成一段摘要，和上一版摘要合并。
  多数请求什么都不做，只有跨阈值才多一次模型调用。
  **摘要只影响模型看到什么，不删任何原文**——历史接口仍能完整取回全部对话。

  注意"窗口"和"触发阈值"是两件事：窗口 12000 之后，一次正常参观
  （30~60 问 ≈ 2200~4400 token）**根本不会溢出**，所以阈值取小也不影响正常使用——
  它只在超长对话（实测约第 289 轮）里才生效，属于安全网。
- 真实 token 用量取自服务端 `usage`，随会话存下来；整个提示词超过
  `PROMPT_TOKEN_ALERT = 200000` 时打告警。
- 指代消解遵循**宁可不改、不要猜错**：只有能确定唯一对象时才改写问句，
  遇到复数代词（它们/这些）、比较并列（分别/两个）、或焦点不唯一，一律原样返回。
- 用户原话与消解结果**分列存储**（`content` / `resolved`），展示与摘要始终用原话。
- 老库会自动迁移（补 `tokens` / `last_prompt_tokens` 列并回填估算值），
  升级后不用删库重建。


## 配置说明

模型相关的所有配置集中在 `app/core/config.py`。
API 密钥建议放到环境变量或本地私密文件里（该文件已在 `.gitignore` 范围内，勿提交）。
