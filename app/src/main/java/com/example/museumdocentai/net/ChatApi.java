package com.example.museumdocentai.net;

import java.io.File;
import java.util.List;

/**
 * 【角色 A 负责】前后端接口约定（契约），真正的实现在 ApiClient 里。
 *
 * 与后端约定的两个接口：
 *
 * 1. POST /api/chat   文本问答
 *    请求 JSON：{ "question": "问题文本", "session_id": "会话编号" }
 *    响应 JSON：{ "answer": "回答", "sources": ["来源1", "来源2"] }
 *    出错 JSON：{ "error": "错误说明", "hint": "给用户看的提示" }
 *
 * 2. POST /api/voice  语音问答（音频直接交给 mimo-v2.5-asr "听"）
 *    请求：multipart/form-data，字段 audio=录音 WAV 文件、session_id=会话编号
 *    响应 JSON：{ "answer": "回答", "sources": [...], "audio_base64": "回答音频(可能为空)" }
 */
public interface ChatApi {

    /**
     * 统一的回调接口：网络请求在后台执行，结果回到主线程再交给界面。
     * - onSuccess：拿到回答文字、资料来源，audio 是回答音频（可为空数组/空引用）
     * - onFailure：拿到一句"可以直接显示给用户"的错误说明
     */
    interface Callback {
        void onSuccess(String answer, List<String> sources, byte[] audio);

        void onFailure(String message);
    }

    /** 文本提问 */
    void sendText(String question, String sessionId, Callback callback);

    /** 语音提问（传入录好的 WAV 文件） */
    void sendVoice(File audioFile, String sessionId, Callback callback);
}
