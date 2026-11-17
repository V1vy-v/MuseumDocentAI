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
 * 2. POST /api/voice  语音问答（音频交给后端做语音识别）
 *    请求：multipart/form-data，字段 audio=录音 WAV 文件、session_id=会话编号
 *    响应 JSON：{ "question": "识别出的提问", "answer": "回答", "sources": [...], "audio_base64": "回答音频" }
 * 3. POST /api/tts    文字转语音（后端新增）
 *    请求 JSON：{ "text": "要朗读的文字" }
 *    响应 JSON：{ "audio_base64": "音频", "format": "wav" }
 *    用于：文字提问时，把回答也朗读出来（配合界面上的"语音播报"开关）
 */
public interface ChatApi {

    /**
     * 统一的回调接口：网络请求在后台执行，结果回到主线程再交给界面。
     * - onSuccess：拿到回答文字、资料来源，audio 是回答音频（可为空数组/空引用）
     * - onFailure：拿到一句"可以直接显示给用户"的错误说明
     */
    interface Callback {
        /**
         * @param answer      回答文本
         * @param sources     资料来源标题（可能为空）
         * @param audio       回答音频（语音提问才有，文字提问为 null）
         * @param recognized  语音提问时后端识别出的问句；文字提问为空串。
         *                    界面用它把"🎤 语音提问"占位换成真正的问题内容。
         */
        void onSuccess(String answer, List<String> sources, byte[] audio, String recognized);

        void onFailure(String message);
    }

    /** 文字转语音的回调 */
    interface TtsCallback {
        /** 合成成功，audio 就是可以播放的音频字节 */
        void onAudio(byte[] audio);

        /** 合成失败（后端没配 TTS、网络断了等），界面降级为只显示文字 */
        void onFailure(String message);
    }

    /** 文本提问 */
    void sendText(String question, String sessionId, Callback callback);

    /** 语音提问（传入录好的 WAV 文件） */
    void sendVoice(File audioFile, String sessionId, Callback callback);

    /** 把一段文字合成语音（朗读回答用） */
    void synthesize(String text, TtsCallback callback);

    /** 设置后端地址；传空字符串表示恢复"自动尝试内置候选地址" */
    void setServerUrl(String url);

    /** 当前设置的后端地址（空字符串表示自动） */
    String getServerUrl();
}
