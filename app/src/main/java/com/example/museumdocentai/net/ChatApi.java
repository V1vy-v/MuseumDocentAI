package com.example.museumdocentai.net;

import com.example.museumdocentai.model.ChatMessage;
import com.example.museumdocentai.model.FilterItem;
import com.example.museumdocentai.model.KbItem;
import com.example.museumdocentai.model.SessionInfo;

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

    // ======== 资料库（手动检索，不经过大模型） ========

    /** 资料检索的回调 */
    interface KbListCallback {
        /**
         * @param items      当前这一页的资料
         * @param total      满足条件的总数（用来判断还有没有下一页）
         * @param provinces  省份筛选项（带数量）
         * @param categories 文物类别筛选项（带数量）
         */
        void onList(List<KbItem> items, int total,
                    List<FilterItem> provinces, List<FilterItem> categories);

        void onFailure(String message);
    }

    /** 打开一份资料原文的回调 */
    interface KbDocCallback {
        /**
         * @param images 资料里引用的实物照片（相对知识库的路径），可能为空
         */
        void onDoc(String title, String meta, String text, List<String> images);

        void onFailure(String message);
    }

    /** 加载图片的回调 */
    interface ImageCallback {
        void onImage(android.graphics.Bitmap bitmap);

        void onFailure(String message);
    }

    /** 取一张资料图片（文物实物照片） */
    void fetchImage(String path, ImageCallback callback);

    /**
     * 按关键词检索资料库。
     *
     * @param query    关键词；留空表示按条件浏览
     * @param kind     "museum"/"artifact"；空串表示全部
     * @param province 省份；空串表示全部
     * @param category 文物类别；空串表示全部
     * @param offset   分页起点（0 表示第一页）
     */
    void searchKb(String query, String kind, String province, String category,
                  int limit, int offset, KbListCallback callback);

    /** 取一份资料的原文（path 就是检索结果里的 path 字段） */
    void openKbDoc(String path, KbDocCallback callback);

    // ======== 流式问答 + 会话历史 ========

    /**
     * 流式问答：后端边生成边推（SSE），界面可以一个字一个字地显示。
     * 失败时调用 onFailure，界面降级为普通请求或提示错误。
     */
    interface StreamCallback {
        /** 先给来源（可能在文字之前就到达），界面可以先显示"来源" */
        void onMeta(List<String> sources);

        /** 收到一段新增文字（要求在主线程调用） */
        void onDelta(String text);

        /** 生成完成，answer 是完整回答 */
        void onDone(String answer);

        void onFailure(String message);
    }

    /** 历史会话列表 */
    interface SessionListCallback {
        void onList(List<SessionInfo> sessions);

        void onFailure(String message);
    }

    /** 某个会话的历史消息（APP 重启后回填界面用） */
    interface MessagesCallback {
        void onMessages(List<ChatMessage> messages);

        void onFailure(String message);
    }

    void streamText(String question, String sessionId, StreamCallback callback);

    void listSessions(int limit, SessionListCallback callback);

    void loadMessages(String sessionId, MessagesCallback callback);

    /** 设置后端地址；传空字符串表示恢复"自动尝试内置候选地址" */
    void setServerUrl(String url);

    /** 当前设置的后端地址（空字符串表示自动） */
    String getServerUrl();
}
