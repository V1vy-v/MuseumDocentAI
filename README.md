# MuseumDocentAI —— 基于 RAG 的博物馆导览问答机器人

安卓 APP + Python 后端的博物馆智能讲解员：支持**语音提问**、结合博物馆资料**精准回答**（带来源引用）、**多轮对话**记忆。

- 技术方案与调整记录：[docs/技术方案.md](docs/技术方案.md)
- 大脑模型：mimo-v2.5-asr（支持语音输入；若无语音输出则另接 TTS API）

## 目录结构（★ = 代码放这里）

```
MuseumDocentAI/
├── app/                                ★ 前端：安卓 APP（角色 A、B 的主战场）
│   └── src/main/java/com/example/museumdocentai/
│       ├── MainActivity.java              页面入口
│       ├── ui/                          ★ 【A】界面与交互：录音按钮、对话气泡、
│       │                                   加载动画、来源引用展示
│       ├── net/                         ★ 【A】网络请求：对接后端 /api/chat、/api/voice
│       ├── model/                       ★ 【A/B 共用】数据结构：消息、回答、来源
│       ├── audio/                       ★ 【B】语音：录音、播报播放、打断、音频焦点
│       └── util/                        ★ 【通用】小工具
│   └── src/test/…                       ★ 【A】UI 测试、【B】语音模块测试
│
├── backend/                            ★ 后端：Python 服务（角色 C、D 的主战场）
│   ├── app/
│   │   ├── main.py                      ★ 【D】服务入口（FastAPI）
│   │   ├── api/                         ★ 【D】对外接口：chat.py（文本）、voice.py（语音）
│   │   ├── services/                    ★ 核心逻辑
│   │   │   ├── llm_client.py            ★ 【D】封装 mimo-v2.5-asr 调用
│   │   │   ├── tts_client.py            ★ 【D】语音合成（mimo 无语音输出时启用）
│   │   │   ├── rag.py                   ★ 【C】检索增强（查询改写、防幻觉、引用来源）
│   │   │   └── memory.py                ★ 【D】多轮对话记忆（历史、指代消解）
│   │   ├── core/config.py               ★ 【D】配置：模型名、API 密钥、服务端口
│   │   └── schemas/chat.py              ★ 【D】请求/响应的数据格式约定
│   ├── knowledge_base/                  ★ 【C】博物馆资料与向量库
│   ├── requirements.txt                 后端依赖清单
│   └── README.md                        后端运行说明
│
├── docs/                               文档：技术方案、测试记录、报告素材
└── README.md                           本文件：项目总览
```

## 分工与代码位置对照

| 角色 | 任务 | 代码位置 |
|---|---|---|
| A | APP 界面与交互 | `app/…/ui/`、`app/…/net/`、`app/…/model/` |
| B | APP 语音交互 | `app/…/audio/`（与 A 在 `model/` 协作） |
| C | RAG 与知识库 | `backend/app/services/rag.py`、`backend/knowledge_base/` |
| D | 模型接入、多轮对话、后端 API | `backend/app/`（api、services、core、schemas） |

## 怎么跑起来

**前端（安卓）**：用 Android Studio 打开本项目根目录 → 等待构建完成 → 连接手机或模拟器运行。
（已验证：Debug/Release 构建、单元测试、Lint 全部通过。）

**后端（Python）**：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 提交代码前注意

- `local.properties`、`.gradle/`、`app/build/`、`pypdf_lib/`、`.tools/` 等**不要提交**（`.gitignore` 已配置好）。
- 提交前先看 `git status`，确认没有把大文件和临时文件加进来。
