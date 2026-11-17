# Web 前端：博物馆导览问答

面向观众的正式对话页面，模仿主流 AI 问答网页的布局：
**左侧对话历史 + 中间对话正文**。与后端的 `backend/static/debug.html`（开发自测用的调试台）是两套东西：

| | 这个页面 | `/debug` 调试台 |
|---|---|---|
面向 | 观众 | 开发者 |
能看到 | 回答、来源、朗读 | 指代消解结果、滚动摘要、token 明细、原始报文 |
技术 | Vue 3 + Vite（有构建） | 单文件原生 JS（零构建） |

## 技术栈

| 项 | 选择 | 为什么 |
|---|---|---|
框架 | **Vue 3**（`<script setup>` + TypeScript） | 单文件组件读起来接近 HTML，团队里没写过后端的人也能改 |
构建 | **Vite 7** | 启动和热更新快，自带 `/api` 反向代理，开发时不用处理跨域 |
Markdown | **marked + DOMPurify** | 模型输出是不可信文本，直接塞 `innerHTML` 有 XSS 风险，必须净化 |
状态 | 一个模块级 `reactive`（不放 pinia） | 状态很浅，少一个依赖就少一处版本冲突 |
样式 | 手写 CSS + CSS 变量 | 深浅色只换一组变量，不引 UI 库，包体小 |

## 快速开始

### 前置条件

| 项 | 要求 | 检查命令 |
|---|---|---|
Node.js | **18 以上**（本项目用 24.13 验证） | `node -v` |
npm | 随 Node 自带（用 11.x 验证过） | `npm -v` |
后端 | 必须同时在跑，否则页面能打开但发不出问答 | 见下一步 |

### 第一步：先起后端（另开一个终端）

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

看到 `[向量库] 就绪 ...` 和 `[启动] 文本模型 ...` 就说明后端好了。
索引已建好时不会重新向量化（日志显示 `本次变更=0`），秒起。

### 第二步：装依赖并启动前端

```powershell
cd web
npm install     # 已配国内镜像（.npmrc），约 7 秒；首次会有 53 个包
npm run dev     # → http://127.0.0.1:5173
```

浏览器打开 **http://127.0.0.1:5173** 即可。左栏是对话历史，中间是问答正文。

### 第三步：确认通了

页面左下角应显示 **「服务正常 · 向量检索」**（绿点）。如果显示「连不上后端」或「关键词模式」，
按下面的表排查。

前端把 `/api/*` 反向代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`），
所以浏览器里前后端是**同源**的，不存在 CORS 问题，也没有改后端一行代码。

### 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
`127.0.0.1:5173` 连不上，但 `localhost:5173` 能开 | Node 把 localhost 解析成 IPv6 `::1`，而 Vite 默认只监听它 | 本项目已显式设 `host: '127.0.0.1'`，重启 `npm run dev` 即可 |
左下角「连不上后端」 | 后端没起，或不在 8000 端口 | 先执行第一步；用 `curl http://127.0.0.1:8000/api/health` 验证 |
左下角「关键词模式」（黄点） | 后端起来了，但向量索引没就绪 | 看后端日志里的 `[向量库]` 行；通常是 `EMBED_API_KEY` 没配 |
`npm install` 卡住不动 | 走了默认官方源 | 项目自带的 `.npmrc` 已指定 `registry.npmmirror.com`，确认它存在；或 `npm install --registry=https://registry.npmmirror.com` |
`npm run dev` 报端口占用 | 5173 被别的进程占了 | 关掉占用的进程，或临时 `npx vite --port 5174` |
手机打不开 | 默认只监听本机 | `npm run dev:lan`，用电脑局域网 IP 访问；后端也要 `--host 0.0.0.0` |

> 用手机在同局域网演示：`npm run dev:lan`，然后打开 `http://<电脑局域网IP>:5173`。

## 其它命令

| 命令 | 作用 |
|---|---|
| `npm run dev` | 开发服务器（热更新） |
| `npm run dev:lan` | 同上，但监听所有网卡，供手机访问 |
| `npm run build` | 构建到 `dist/`（`base: './'`，可以挂到任意子路径） |
| `npm run typecheck` | `vue-tsc` 类型检查（当前零错误） |

## 目录结构

```
web/
├── index.html            入口（挂载 #app）
├── vite.config.ts        dev 端口 / /api 代理 / 构建配置
├── package.json
├── .npmrc                国内镜像源
└── src/
    ├── main.ts
    ├── App.vue           布局：侧栏 + 顶栏 + 消息区 + 输入区
    ├── types.ts          与后端 schemas 对应的类型
    ├── api/
    │   ├── client.ts     统一请求：把 {error,hint} 和 {detail:[...]} 归一成 ApiError
    │   └── chat.ts       SSE 流式解析（fetch + ReadableStream，不是 EventSource）
    ├── stores/
    │   └── chat.ts       全部状态与动作：会话列表、打开/新建/删除、发送、语音、朗读
    ├── components/
    │   ├── AppSidebar.vue  左侧历史（按今天/昨天/近 7 天/更早分组、搜索、两步确认删除）
    │   ├── ChatMessage.vue 气泡、markdown、来源胶囊、复制、朗读
    │   ├── Composer.vue    输入框、Enter 发送、录音按钮
    │   └── EmptyState.vue  空状态与推荐问题
    ├── utils/
    │   ├── markdown.ts   marked + DOMPurify
    │   ├── audio.ts      MediaRecorder 的 webm → 16kHz 单声道 WAV
    │   └── format.ts     相对时间与会话分组
    └── styles/main.css   全部样式 + 深浅色变量
```

## 用到的后端接口

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 启动时探活，底栏显示"向量检索 / 关键词模式" |
| `GET /api/sessions?limit=50` | 左侧历史列表 |
| `POST /api/sessions` | 首次发送时懒建会话（避免产生空会话） |
| `GET /api/sessions/{id}/messages` | 点开某个历史会话 |
| `DELETE /api/sessions/{id}` | 删除会话（幂等） |
| `POST /api/chat/stream` | **流式回答**：`meta` → `delta`×N → `done`，出错发 `error` |
| `POST /api/voice` | 语音提问：识别 + 回答 + 播报一次返回 |
| `POST /api/tts` | 朗读单段回答 |
| `GET /api/kb/{路径}` | 来源胶囊点开的资料原文 |

## 几个实现上踩过 / 避开的坑

1. **不能用 `EventSource`**：它只能发 GET，而这个接口要 POST JSON body。
   所以用 `fetch` + `ReadableStream` 自己按空行切 SSE 事件。
2. **`TextDecoder` 必须传 `{stream:true}`**：一个汉字可能被切在两个网络块之间，
   不加这个参数会在块边界解码出乱码。
3. **改 reactive 数组里刚 push 进去的对象要读回代理**：
   `chat.messages.push(m)` 之后再改 `m.content` 不会触发渲染，必须
   `const bot = chat.messages[chat.messages.length-1]` 再改 `bot.content`。
4. **输入法回车不能当发送**：中文选词时按回车会误发，判断 `e.isComposing`。
5. **流式期间用纯文本、定稿才渲染 markdown**：每个 delta 都重排一次 DOM 会闪。
6. **删除用两步确认而不是 `confirm()`**：连续弹窗会被浏览器静默屏蔽，
   之后按钮彻底失效且没有任何报错（调试台里已经踩过一次）。
7. **`base: './'`**：写成 `'/'` 时挂到子路径会白屏，因为资源会去根路径找。
