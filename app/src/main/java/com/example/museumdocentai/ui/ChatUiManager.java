package com.example.museumdocentai.ui;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.R;
import com.example.museumdocentai.audio.AudioPlayer;
import com.example.museumdocentai.audio.VoiceRecorder;
import com.example.museumdocentai.model.ChatMessage;
import com.example.museumdocentai.net.ApiClient;
import com.example.museumdocentai.net.ChatApi;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】界面与交互管理（界面逻辑都集中在这里）。
 *
 * 做什么：
 * 1. 管理中间的对话消息列表（RecyclerView + ChatAdapter）；
 * 2. 处理两种提问入口：打字发送、语音提问；
 * 3. 管理状态提示：等待回答显示"思考中…"、录音时按钮变红并提示；
 * 4. 打断机制：AI 正在播报语音时点录音按钮，立即停播报再开始录音；
 * 5. 出错时用 Toast 或红色气泡提示。
 *
 * MainActivity 只负责把按钮点击"转告"进来，其余都在这个类里完成。
 */
public class ChatUiManager {

    private final Activity activity;
    /** 会话编号：切历史会话时会变，所以不能是 final */
    private String sessionId;

    // 界面上的各个控件
    private final RecyclerView recyclerMessages;
    private final LinearLayout layoutStatus;
    private final ProgressBar progressThinking;
    private final TextView textStatus;
    private final EditText editQuestion;
    private final Button btnSend;
    private final Button btnMic;
    /** 输入区里的"语音播报"胶囊按钮（替代原来的 Switch） */
    private final Button btnVoice;
    private final Button btnSettings;
    /** 空对话时的引导卡片（列几个"试试问我"） */
    private final View layoutEmpty;

    /** 语音提问的占位气泡：拿到后端识别文本后替换成真正的问题内容 */
    private ChatMessage voiceBubble;

    /** 本地设置：记住"语音播报"开关的状态 */
    private static final String PREFS_NAME = "docent_prefs";
    private static final String KEY_VOICE_REPLY = "voice_reply";

    // 对话数据与它的"画笔"
    private final List<ChatMessage> messages = new ArrayList<>();
    private final ChatAdapter adapter;

    // 干活的三个模块
    private final ChatApi apiClient;
    private final VoiceRecorder recorder;
    private final AudioPlayer player;

    /** 是否正在录音 */
    private boolean isRecording = false;

    /** 语音按钮原来的颜色（录音结束后恢复用） */
    private ColorStateList originalMicTint;

    public ChatUiManager(Activity activity, String sessionId) {
        this.activity = activity;
        this.sessionId = sessionId;

        // 找到界面控件
        recyclerMessages = activity.findViewById(R.id.recycler_messages);
        layoutStatus = activity.findViewById(R.id.layout_status);
        progressThinking = activity.findViewById(R.id.progress_thinking);
        textStatus = activity.findViewById(R.id.text_status);
        editQuestion = activity.findViewById(R.id.edit_question);
        btnSend = activity.findViewById(R.id.btn_send);
        btnMic = activity.findViewById(R.id.btn_mic);

        // 消息列表：LinearLayoutManager 就是普通的从上往下一条条排列
        adapter = new ChatAdapter(activity, messages);
        recyclerMessages.setLayoutManager(new LinearLayoutManager(activity));
        recyclerMessages.setAdapter(adapter);

        // 网络、录音、播放三个模块（录音结果通过 recorderListener 送回来）
        apiClient = new ApiClient(activity);
        player = new AudioPlayer(activity);
        recorder = new VoiceRecorder(activity, recorderListener);

        // 输入区里的"语音播报"胶囊：默认打开，关掉后只显示文字不朗读
        btnVoice = activity.findViewById(R.id.btn_voice);
        refreshVoicePill();
        btnVoice.setOnClickListener(v -> toggleVoiceReply());

        // 抽屉底部的"服务器"按钮：改后端地址（真机测试要填电脑的局域网 IP）
        btnSettings = activity.findViewById(R.id.btn_drawer_settings);
        if (btnSettings != null) {
            btnSettings.setOnClickListener(v -> showServerDialog());
        }

        // 空态引导：没有消息时显示几个示例问题，点一下直接提问
        layoutEmpty = activity.findViewById(R.id.layout_empty);
        bindSuggestion(R.id.btn_suggest_1);
        bindSuggestion(R.id.btn_suggest_2);
        bindSuggestion(R.id.btn_suggest_3);
        updateEmptyState();
    }

    /** 把"示例问题"按钮绑定成：填入输入框并直接发送 */
    private void bindSuggestion(int viewId) {
        View view = activity.findViewById(viewId);
        if (view != null) {
            view.setOnClickListener(v -> {
                String text = ((Button) view).getText().toString();
                editQuestion.setText(text);
                onSendClicked();
            });
        }
    }

    /** 消息列表空/非空时切换引导卡片的显示 */
    private void updateEmptyState() {
        if (layoutEmpty != null) {
            layoutEmpty.setVisibility(messages.isEmpty() ? View.VISIBLE : View.GONE);
        }
    }

    // ================== 设置：语音播报开关 / 服务器地址 ==================

    /** 切换语音播报（输入区的胶囊按钮） */
    public void toggleVoiceReply() {
        boolean next = !isVoiceReplyEnabled();
        setVoiceReplyEnabled(next);
        if (!next && player.isPlaying()) {
            player.stop();          // 关掉开关时立刻停止正在播放的语音
        }
        refreshVoicePill();
    }

    /** 胶囊文案跟着开关状态变：🔊 / 🔇 */
    private void refreshVoicePill() {
        if (btnVoice != null) {
            btnVoice.setText(isVoiceReplyEnabled()
                    ? R.string.pill_voice_on : R.string.pill_voice_off);
        }
    }

    /** 语音播报是否打开（用户的选择会记住，下次启动沿用） */
    private boolean isVoiceReplyEnabled() {
        return prefs().getBoolean(KEY_VOICE_REPLY, true);
    }

    private void setVoiceReplyEnabled(boolean enabled) {
        prefs().edit().putBoolean(KEY_VOICE_REPLY, enabled).apply();
    }

    private SharedPreferences prefs() {
        return activity.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    /** 弹窗填写后端地址；留空表示自动（模拟器默认地址） */
    public void showServerDialog() {
        final EditText input = new EditText(activity);
        input.setHint(R.string.dialog_server_hint);
        input.setText(apiClient.getServerUrl());
        input.setSingleLine(true);

        new AlertDialog.Builder(activity)
                .setTitle(R.string.dialog_server_title)
                .setMessage(R.string.dialog_server_message)
                .setView(input)
                .setPositiveButton(R.string.dialog_ok, (dialog, which) -> {
                    apiClient.setServerUrl(input.getText().toString());
                    showToast(activity.getString(R.string.toast_server_saved));
                })
                .setNegativeButton(R.string.dialog_cancel, null)
                .show();
    }

    // ================== 对外入口（MainActivity 转发） ==================

    /** 点"发送"按钮：发送文本问题 */
    public void onSendClicked() {
        String question = editQuestion.getText().toString().trim();
        if (question.isEmpty()) {
            return;
        }
        editQuestion.getText().clear();

        // 先把用户的问题显示到列表里，再交给后端
        adapter.add(new ChatMessage(ChatMessage.Role.USER, question, null, ChatMessage.Status.DONE));
        updateEmptyState();
        scrollToBottom();
        askBackendStreaming(question);
    }

    /**
     * 文本提问：走流式接口（/api/chat/stream），边生成边显示。
     *
     * 为什么单独一条路：语音提问必须等整段音频一起回来，没法流式；
     * 文本提问则可以先把字铺出来，首字延迟从 1~3 秒降到 0.3 秒左右。
     */
    private void askBackendStreaming(String question) {
        final ChatMessage pending = new ChatMessage(
                ChatMessage.Role.AI, "", null, ChatMessage.Status.LOADING);
        adapter.add(pending);
        updateEmptyState();
        scrollToBottom();
        showThinking();

        final StringBuilder buffer = new StringBuilder();
        apiClient.streamText(question, sessionId, new ChatApi.StreamCallback() {
            @Override
            public void onMeta(List<String> sources) {
                if (sources != null && !sources.isEmpty()) {
                    pending.setSources(sources);
                    refreshMessage(pending);
                }
            }

            @Override
            public void onDelta(String text) {
                if (text == null || text.isEmpty()) {
                    return;
                }
                hideStatus();      // 已经开始出字了，"思考中"就撤掉
                buffer.append(text);
                pending.setText(buffer.toString());
                pending.setStatus(ChatMessage.Status.DONE);
                refreshMessage(pending);
                scrollToBottom();
            }

            @Override
            public void onDone(String answer) {
                String finalText = (answer == null || answer.isEmpty())
                        ? buffer.toString() : answer;
                pending.setText(finalText);
                pending.setStatus(ChatMessage.Status.DONE);
                refreshMessage(pending);
                scrollToBottom();
                hideStatus();
                // 语音播报：和以前一样，开关关掉就只显示文字
                if (isVoiceReplyEnabled() && !finalText.isEmpty()) {
                    speak(finalText);
                }
            }

            @Override
            public void onFailure(String message) {
                pending.setText(message);
                pending.setStatus(ChatMessage.Status.ERROR);
                refreshMessage(pending);
                scrollToBottom();
                hideStatus();
                showToast(message);
            }
        });
    }

    // ================== 历史会话 ==================

    /** 切到某个历史会话：把后端存的消息拉回来铺到界面上 */
    public void loadHistorySession(String targetSessionId) {
        apiClient.loadMessages(targetSessionId, new ChatApi.MessagesCallback() {
            @Override
            public void onMessages(List<ChatMessage> loaded) {
                sessionId = targetSessionId;
                messages.clear();
                messages.addAll(loaded);
                adapter.notifyDataSetChanged();
                updateEmptyState();
                if (!messages.isEmpty()) {
                    scrollToBottom();
                }
            }

            @Override
            public void onFailure(String message) {
                showToast(message);
            }
        });
    }

    /** 开一个新对话：清空界面，换一个新会话编号 */
    public void startNewSession(String newSessionId) {
        sessionId = newSessionId;
        messages.clear();
        adapter.notifyDataSetChanged();
        updateEmptyState();
    }

    /** 点麦克风按钮：没在录就开始录，正在录就停止 */
    public void onMicClicked() {
        if (isRecording) {
            recorder.stop();
            return;
        }
        // 打断机制：AI 正在说话（播报）时，先停播报再录音
        if (player.isPlaying()) {
            player.stop();
        }
        recorder.start();
    }

    /** 用户拒绝了麦克风权限 */
    public void onAudioPermissionDenied() {
        showToast(activity.getString(R.string.toast_permission_denied));
    }

    /** 页面销毁：释放录音和播放资源 */
    public void release() {
        recorder.release();
        player.release();
    }

    // ================== 提问后端的统一流程 ==================

    /**
     * 发起一次提问：先放一条"思考中…"的占位气泡，等后端回来再填真实内容。
     * question 不为空 → 文本提问；voiceFile 不为空 → 语音提问。
     */
    private void askBackend(String question, File voiceFile) {
        final ChatMessage pending = new ChatMessage(
                ChatMessage.Role.AI, "", null, ChatMessage.Status.LOADING);
        adapter.add(pending);
        scrollToBottom();
        showThinking();

        ChatApi.Callback callback = new ChatApi.Callback() {
            @Override
            public void onSuccess(String answer, List<String> sources, byte[] audio, String recognized) {
                // 语音提问：把"🎤 语音提问"占位换成识别出的真实问题（修复"看不到自己说了什么"）
                if (voiceBubble != null) {
                    ChatMessage bubble = voiceBubble;
                    voiceBubble = null;
                    String spoken = recognized == null ? "" : recognized.trim();
                    if (!spoken.isEmpty()) {
                        bubble.setText("🎤 " + spoken);
                        refreshMessage(bubble);
                    }
                }
                // 把占位气泡替换成真实回答
                pending.setText(answer);
                pending.setSources(sources);
                pending.setStatus(ChatMessage.Status.DONE);
                refreshMessage(pending);
                scrollToBottom();
                hideStatus();
                // 语音播报开关关掉：只显示文字，不播放任何声音
                if (!isVoiceReplyEnabled()) {
                    return;
                }
                if (audio != null && audio.length > 0) {
                    // 语音提问：后端把答案音频一起带回来了，直接播
                    player.play(audio, playbackListener);
                } else if (answer != null && !answer.isEmpty()) {
                    // 文字提问：后端只返回文字，再调 /api/tts 把回答读出来
                    speak(answer);
                }
            }

            @Override
            public void onFailure(String message) {
                voiceBubble = null;     // 失败时占位气泡保持原样，下次提问重新记录
                // 出错：红色气泡 + Toast 提示
                pending.setText(message);
                pending.setStatus(ChatMessage.Status.ERROR);
                refreshMessage(pending);
                scrollToBottom();
                hideStatus();
                showToast(message);
            }
        };

        if (voiceFile != null) {
            apiClient.sendVoice(voiceFile, sessionId, callback);
        } else {
            apiClient.sendText(question, sessionId, callback);
        }
    }

    /** 把一段回答文字合成语音并播放（文字提问时用；失败只提示，不影响看文字答案） */
    private void speak(String text) {
        apiClient.synthesize(text, new ChatApi.TtsCallback() {
            @Override
            public void onAudio(byte[] audio) {
                // 合成期间用户可能把开关关掉了，再确认一次
                if (audio != null && audio.length > 0 && isVoiceReplyEnabled()) {
                    player.play(audio, playbackListener);
                }
            }

            @Override
            public void onFailure(String message) {
                showToast(message);
            }
        });
    }

    // ================== 录音的回调（VoiceRecorder 送来） ==================

    private final VoiceRecorder.Listener recorderListener = new VoiceRecorder.Listener() {
        @Override
        public void onRecordingStarted() {
            isRecording = true;
            // 语音按钮变红、文字换成"停止"
            originalMicTint = btnMic.getBackgroundTintList();
            btnMic.setBackgroundTintList(ColorStateList.valueOf(Color.parseColor("#D32F2F")));
            btnMic.setText(R.string.btn_record_stop);
            showStatus(activity.getString(R.string.status_recording), false);
        }

        @Override
        public void onRecordingFinished(File wavFile) {
            isRecording = false;
            restoreMicButton();
            hideStatus();
            // 用户的语音提问先显示一条占位消息，识别结果回来后替换成真实问题
            ChatMessage bubble = new ChatMessage(ChatMessage.Role.USER,
                    activity.getString(R.string.voice_message_label),
                    null, ChatMessage.Status.DONE);
            voiceBubble = bubble;
            adapter.add(bubble);
            askBackend(null, wavFile);
        }

        @Override
        public void onRecordingFailed(String message) {
            isRecording = false;
            restoreMicButton();
            hideStatus();
            showToast(message);
        }
    };

    /** 播放的回调（AudioPlayer 送来） */
    private final AudioPlayer.Listener playbackListener = new AudioPlayer.Listener() {
        @Override
        public void onPlaybackFinished() {
            // 播完不用特别处理，等待用户下一次提问
        }

        @Override
        public void onPlaybackFailed(String message) {
            showToast(message);
        }
    };

    // ================== 界面状态的小工具 ==================

    /** 某条消息内容变了，让列表只刷新那一条 */
    private void refreshMessage(ChatMessage message) {
        int index = messages.indexOf(message);
        if (index >= 0) {
            adapter.update(index);
        }
    }

    /** 显示"思考中…"（带转圈），并暂时禁用发送按钮防重复点击 */
    private void showThinking() {
        showStatus(activity.getString(R.string.status_thinking), true);
        btnSend.setEnabled(false);
    }

    /** 显示一行状态提示；showProgress 决定要不要显示转圈 */
    private void showStatus(String text, boolean showProgress) {
        textStatus.setText(text);
        textStatus.setVisibility(View.VISIBLE);
        progressThinking.setVisibility(showProgress ? View.VISIBLE : View.GONE);
        layoutStatus.setVisibility(View.VISIBLE);
    }

    /** 隐藏状态提示、恢复发送按钮 */
    private void hideStatus() {
        layoutStatus.setVisibility(View.GONE);
        progressThinking.setVisibility(View.GONE);
        textStatus.setVisibility(View.GONE);
        btnSend.setEnabled(true);
    }

    /** 把列表滚到最新一条 */
    private void scrollToBottom() {
        recyclerMessages.scrollToPosition(messages.size() - 1);
    }

    /** 恢复语音按钮的外观（停止录音后调用） */
    private void restoreMicButton() {
        btnMic.setText(R.string.btn_record);
        btnMic.setBackgroundTintList(originalMicTint);
    }

    /** 弹一个简短提示 */
    private void showToast(String message) {
        Toast.makeText(activity, message, Toast.LENGTH_SHORT).show();
    }
}
