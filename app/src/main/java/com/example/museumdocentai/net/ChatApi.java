package com.example.museumdocentai.net;

/**
 * 【角色 A 负责】前后端接口约定（占位骨架）
 *
 * 与后端约定的两个接口（详见 docs/技术方案.md）：
 *
 * 1. POST /api/chat   文本问答
 *    请求：{ 问题文本, 会话编号 }
 *    响应：{ 回答文本, 资料来源列表 }
 *
 * 2. POST /api/voice  语音问答（新版方案：音频直接交给 mimo-v2.5-asr）
 *    请求：录音文件 + 会话编号
 *    响应：{ 回答文本, 资料来源列表, 回答音频（可选） }
 */
public interface ChatApi {
    // TODO(角色A)：定义上面两个接口的调用方法
}
