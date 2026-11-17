# 后端：博物馆导览问答服务（角色 C、D 的主战场）

技术栈：Python + FastAPI（轻量的 Web 服务框架，浏览器/APP 都能调用）

## 怎么跑起来

```bash
cd backend
pip install -r requirements.txt      # 含 zvec（向量库，win 包约 11MB）
cp .env.example .env                 # 然后把两个密钥填进去
uvicorn app.main:app --port 8000     # 开发时可以加 --reload
```

`.env` 里的两个密钥分工不同：

| 变量 | 用途 | 不填会怎样 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 文本问答、摘要、语音识别 | 问答直接 502 |
| `ARK_API_KEY` | 文档向量化（检索用） | 服务照常起，但检索退回关键词模式 |

**向量索引会自动构建，不需要任何手工命令**：启动时按 `knowledge_base/` 的资料
切块 + 向量化，写进 `backend/data/zvec_kb/`（已 gitignore，可随时删掉重建）。
当前 616 份资料约 5726 块，首次建库约 **55 秒**，之后只重建改过的文件（秒级）。
日志会告诉你走的是哪条路：

```
[向量化] 5726/5726 段  已用 49.7s
[向量库] 就绪 dim=1024 文件=616 本次变更=616 新增块=5726
[启动] 文本模型 deepseek-flash @ https://api.deepseek.com
```

如果看到 `[向量库] 未配置 EMBED_API_KEY / ARK_API_KEY → 检索退回关键词模式`，就是 key 没配好。

> ⚠️ 只能单进程跑（别用 `--workers 2`）。向量库是进程内数据库，一个索引目录只能被一个进程打开。

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
- **语音提问**：点「🎤 语音提问」开始录音，再点一次结束并提交。
  浏览器录的是 webm，页面会先在本地转成 16kHz WAV 再发给 `/api/voice`，
  所以整条语音链路（识别 → 检索 → 回答 → 播报）都能在调试台里直接试听
- **语音输出**：每条回答下面有个「🔊 朗读」，点一下就走 `/api/tts` 合成并播放；
  勾上「自动朗读」则回答一生成完就自动出声（包括流式输出）
- **来源气泡**：命中馆内资料时，回答下方出现灰色小胶囊，点开就是资料原文
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
| `DENSE_MAX_DISTANCE` | 0.62 | **检索相关性闸门**（COSINE 距离，越小越像）。调大=召回更多但更容易混进不相关的，调小=更严格 |
| `RAG_VECTOR_ENABLED` | 1 | 置 `0` 完全关闭向量检索（不建索引、不调 embedding），直接用关键词模式 |
| `VECTOR_DIR` | `backend/data/zvec_kb` | 索引目录位置 |

**向量化可以换供应商**（都走 OpenAI 兼容的 `/embeddings`）。下面三个不填就回落到
`ARK_*`，所以只配了火山的人不用改任何东西：

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `EMBED_BASE_URL` | 同 `ARK_BASE_URL` | 向量化接口地址 |
| `EMBED_API_KEY` | 同 `ARK_API_KEY` | 向量化密钥 |
| `EMBED_MODEL` | 同 `ARK_EMBED_MODEL` | 向量化模型名 |
| `EMBED_BATCH` | 100 | 一次请求塞多少段。**火山 Ark 实测硬上限 10**，用 Ark 时必须设回 10 |
| `EMBED_DELAY_SECONDS` | 0.35 | 批间间隔，仅建库时生效 |

> 为什么不直接改 `ARK_*`：`ARK_BASE_URL` / `ARK_API_KEY` 同时是**文本模型的备用通道**
> （DeepSeek 不可用时切火山，见 `llm_client._text_target`）。把它们指向别家会让
> 这条备用通道带着不匹配的模型名去调用，等于悄悄失效。

实测对比（616 份资料 / 5726 块，2026-11 本机）：

| 供应商 | 维度 | 批量 | 单批耗时 | 建库总耗时 | 限频 |
|---|---|---|---|---|---|
| 火山 `doubao-embedding-vision` | 2048 | 10（硬上限） | ~2.1s | 约 20 分钟 | 大批量必现 429 |
| SiliconFlow `BAAI/bge-m3` | 1024 | 100 | ~0.86s | **54.9 秒** | 未遇到 |

换模型会改变向量维度，`vector_store` 检测到维度变化后**自动重建索引**
（`_reset_disk`），不需要手工删目录。检索效果上 Ark 略优（19 条描述式查询的
MRR 0.961 vs 0.912），bge-m3 的已知弱项是"用风格描述指代某幅具体画作"这类问法。

> ⚠️ **换模型必须重标 `DENSE_MAX_DISTANCE`**：这个阈值是距离，随模型变，不可移植。
> 在 bge-m3 上实测正例与负例的距离分布**有重叠**（正例最近候选 0.230~0.553、
> 负例 0.394~0.540），不存在干净的分界。折中取 0.46（正例 14/15 放行、
> 闲聊 5/15 漏放）。用 bge-m3 时请写进 `.env` 覆盖，不要改 `config.py` 的默认值。

值写错（比如填了非数字）会退回默认值，不会把服务带崩。

## 目录说明

| 位置 | 谁负责 | 放什么 |
|---|---|---|
| `app/main.py` | D | 服务入口；启动时建表、清理过期会话、建/更新向量索引（lifespan） |
| `app/api/` | D | 对外接口：`chat.py` 文本问答、`voice.py` 语音问答、`sessions.py` 会话管理、`kb.py` 资料原文浏览 |
| `app/services/llm_client.py` | D | 封装 DeepSeek 的调用（文本问答 / 流式 / 摘要 / 语音识别） |
| `app/services/tts_client.py` | D | 语音合成（DeepSeek /v1/tools/tts，返回 WAV；失败时降级为只返回文字） |
| `app/services/rag.py` | C | 检索门面：选路、融合、防幻觉、给出来源与原文链接 |
| `app/services/vector_store.py` | C | zvec 向量库：建库、增量同步、向量距离闸门 + BM25 混合检索 |
| `app/services/chunker.py` | C | 把资料按 Markdown 结构切成检索单元 |
| `app/services/embeddings.py` | C | 文本向量化（OpenAI 兼容，供应商可换：默认火山 Ark，当前用 SiliconFlow bge-m3） |
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
| `docs/` | D | 后端文档：`后端README.md`（需求与实现状态）、`接口文档.md`（给前端）、`记忆系统与指代消解方案.md`；跨前后端的全局文档放仓库根的 `docs/` |
| `data/` | — | 运行时生成的会话数据库（已 gitignore，**不要提交**） |

## 接口清单

| 接口 | 说明 | 前端要不要调 |
|---|---|---|
| `POST /api/chat` | 文本问答 `{question, session_id}` → `{answer, sources}` | 已在用 |
| `POST /api/chat/stream` | **流式问答（SSE）**：`meta` → `delta`* → `done`/`error` | **可选**（接了才有打字机效果） |
| `POST /api/voice` | 语音问答（multipart：`audio` + `session_id`）→ `{question, answer, sources, sources_detail, audio_base64}` | 已在用 |
| `POST /api/tts` | 文字转语音 `{text}` → `{audio_base64, format}`，给"文本回答也朗读"用 | **可选** |
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
