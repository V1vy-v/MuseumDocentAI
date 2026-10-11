package com.example.museumdocentai.ui;

import android.app.Activity;
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
    private final String sessionId;

    // 界面上的各个控件
    private final RecyclerView recyclerMessages;
    private final LinearLayout layoutStatus;
    private final ProgressBar progressThinking;
    private final TextView textStatus;
    private final EditText editQuestion;
    private final Button btnSend;
    private final Button btnMic;

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
        scrollToBottom();
        askBackend(question, null);
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
            public void onSuccess(String answer, List<String> sources, byte[] audio) {
                // 把占位气泡替换成真实回答
                pending.setText(answer);
                pending.setSources(sources);
                pending.setStatus(ChatMessage.Status.DONE);
                refreshMessage(pending);
                scrollToBottom();
                hideStatus();
                // 后端带回回答音频就播出来（audio 为空表示不播报，正常情况）
                if (audio != null && audio.length > 0) {
                    player.play(audio, playbackListener);
                }
            }

            @Override
            public void onFailure(String message) {
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
            // 用户的语音提问显示成一条消息，然后把录音交给后端
            adapter.add(new ChatMessage(ChatMessage.Role.USER,
                    activity.getString(R.string.voice_message_label),
                    null, ChatMessage.Status.DONE));
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
