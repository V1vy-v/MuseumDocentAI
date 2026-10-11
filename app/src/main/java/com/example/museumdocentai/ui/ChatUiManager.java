package com.example.museumdocentai.ui;

/**
 * 【角色 A 负责】界面与交互管理（占位骨架，实现待后续开发）
 *
 * 任务清单（对应项目分工的 A 部分）：
 * 1. 录音按钮：按下开始录音，显示录音状态；点击结束。
 * 2. 对话气泡：右侧=用户提问，左侧=AI 回答，列表可滚动，展示历史对话。
 * 3. 加载动画：等待后端回答时显示"思考中…"。
 * 4. 来源引用：在 AI 回答气泡下方展示资料来源（RAG 检索到的依据）。
 * 5. 打断机制：播报语音时再次录音，立即停止播报。
 *
 * 界面布局文件位置：app/src/main/res/layout/（对话气泡建议另建 item_chat_message.xml）
 *
 * 后续实现时大致会有这些方法（先记住名字即可，语法不用管）：
 * - showUserMessage(...)   把用户的提问加到对话列表
 * - showAiMessage(...)     把 AI 的回答（含来源）加到对话列表
 * - showLoading(...)       显示/隐藏"思考中"动画
 */
public class ChatUiManager {
    // TODO(角色A)：后续实现
}
