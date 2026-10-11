package com.example.museumdocentai.audio;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;

import androidx.core.content.ContextCompat;

import com.example.museumdocentai.R;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * 【角色 B 负责】录音模块。
 *
 * 做什么：用手机麦克风录一段 16kHz / 16位 / 单声道 的声音，
 * 停止时把它打包成 WAV 文件（存到应用缓存目录），通过回调交给界面上传给后端。
 * 后端的 mimo-v2.5-asr 会直接"听"这段音频，所以这里不用集成任何识别 SDK。
 *
 * 录音规则：
 * - 最短 2 秒：太短当成误触，提示"说话时间太短"；
 * - 最长 60 秒：到时自动停止并返回录音。
 *
 * 使用方式（界面那边）：
 *   recorder.start();  // 开始
 *   recorder.stop();   // 停止，稍后回调 onRecordingFinished(文件)
 */
public class VoiceRecorder {

    /** 录音过程的回调（都回到主线程，可以直接更新界面） */
    public interface Listener {
        /** 录音开始了（界面把按钮变红、显示提示） */
        void onRecordingStarted();

        /** 录音完成，wavFile 是录好的 WAV 文件 */
        void onRecordingFinished(File wavFile);

        /** 录音失败或太短，message 是可以直接显示的提示 */
        void onRecordingFailed(String message);
    }

    /** 采样率 16kHz——语音识别最常用的规格 */
    public static final int SAMPLE_RATE = 16000;

    private static final long MIN_DURATION_MS = 2000;   // 最短 2 秒
    private static final long MAX_DURATION_MS = 60000;  // 最长 60 秒自动停

    private final Context context;
    private final Listener listener;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    /** 手机麦克风的系统组件 */
    private AudioRecord audioRecord;

    /** 是否正在录音（多线程共享，用 volatile 保证两边看到的值一致） */
    private volatile boolean recording;

    /** 页面是否已销毁（销毁后不再发回调） */
    private volatile boolean released;

    public VoiceRecorder(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
    }

    /** 开始录音 */
    public void start() {
        if (recording || released) {
            return;
        }

        // 先确认麦克风权限还在（用户可能在系统设置里关掉），没有就直接提示
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            notifyFailed(context.getString(R.string.toast_permission_denied));
            return;
        }

        // 先算出系统要求的最小缓冲区，再按它创建录音组件
        int minBuffer = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minBuffer <= 0) {
            notifyFailed(context.getString(R.string.toast_record_failed));
            return;
        }
        try {
            audioRecord = new AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuffer * 2);
        } catch (SecurityException e) {
            // 权限刚好被系统收回的极端情况
            audioRecord = null;
            notifyFailed(context.getString(R.string.toast_permission_denied));
            return;
        }
        if (audioRecord == null || audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
            releaseAudioRecord();
            notifyFailed(context.getString(R.string.toast_record_failed));
            return;
        }

        recording = true;
        notifyStarted();
        audioRecord.startRecording();

        // 后台线程：一边录一边把声音数据存到内存，直到停止或录满 60 秒
        final AudioRecord record = audioRecord;
        new Thread(() -> {
            ByteArrayOutputStream pcm = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            long startAt = System.currentTimeMillis();
            while (recording) {
                int n = record.read(buffer, 0, buffer.length);
                if (n > 0) {
                    pcm.write(buffer, 0, n);
                }
                if (System.currentTimeMillis() - startAt >= MAX_DURATION_MS) {
                    recording = false; // 到 60 秒自动停
                }
            }
            long durationMs = System.currentTimeMillis() - startAt;
            byte[] data = pcm.toByteArray();
            releaseAudioRecord();

            // 太短当成误触
            if (durationMs < MIN_DURATION_MS) {
                notifyFailed(context.getString(R.string.toast_record_too_short));
                return;
            }

            // 加上 WAV 文件头写到缓存目录
            try {
                File wavFile = new File(context.getCacheDir(),
                        "record_" + System.currentTimeMillis() + ".wav");
                writeWavFile(wavFile, data);
                mainHandler.post(() -> {
                    if (!released) {
                        listener.onRecordingFinished(wavFile);
                    }
                });
            } catch (IOException e) {
                notifyFailed(context.getString(R.string.toast_record_failed));
            }
        }).start();
    }

    /** 停止录音（录好的文件稍后通过 onRecordingFinished 回调返回） */
    public void stop() {
        recording = false;
    }

    /** 页面销毁时调用：停止录音并释放麦克风 */
    public void release() {
        released = true;
        recording = false;
        releaseAudioRecord();
    }

    // ======== 内部工具方法 ========

    /** 释放麦克风（重复调用没关系） */
    private void releaseAudioRecord() {
        if (audioRecord != null) {
            try {
                audioRecord.stop();
            } catch (Exception ignored) {
                // 还没开始录就停止会报错，忽略即可
            }
            audioRecord.release();
            audioRecord = null;
        }
    }

    /** 通知界面：录音开始 */
    private void notifyStarted() {
        mainHandler.post(() -> {
            if (!released) {
                listener.onRecordingStarted();
            }
        });
    }

    /** 通知界面：录音失败 */
    private void notifyFailed(String message) {
        mainHandler.post(() -> {
            if (!released) {
                listener.onRecordingFailed(message);
            }
        });
    }

    /**
     * 把原始声音数据写成标准 WAV 文件：
     * WAV = 44 字节的"文件头"（描述格式） + 声音数据本身。
     * 后端要求 WAV 格式，所以这里补上文件头。
     */
    private void writeWavFile(File file, byte[] pcm) throws IOException {
        byte[] header = new byte[44];
        writeString(header, 0, "RIFF");
        writeIntLE(header, 4, 36 + pcm.length);     // 文件总长度
        writeString(header, 8, "WAVE");
        writeString(header, 12, "fmt ");
        writeIntLE(header, 16, 16);                  // 声音格式块的长度
        writeShortLE(header, 20, (short) 1);         // 编码：PCM
        writeShortLE(header, 22, (short) 1);         // 声道数：单声道
        writeIntLE(header, 24, SAMPLE_RATE);         // 采样率
        writeIntLE(header, 28, SAMPLE_RATE * 2);     // 每秒字节数（16位单声道 = 采样率×2）
        writeShortLE(header, 32, (short) 2);         // 每个采样占 2 字节
        writeShortLE(header, 34, (short) 16);        // 位深 16
        writeString(header, 36, "data");
        writeIntLE(header, 40, pcm.length);          // 声音数据长度

        FileOutputStream out = new FileOutputStream(file);
        out.write(header);
        out.write(pcm);
        out.close();
    }

    /** 往字节数组里写一段文字（WAV 文件头用） */
    private static void writeString(byte[] target, int offset, String value) {
        for (int i = 0; i < value.length(); i++) {
            target[offset + i] = (byte) value.charAt(i);
        }
    }

    /** 往字节数组里写一个整数（WAV 用小端格式：低字节在前） */
    private static void writeIntLE(byte[] target, int offset, int value) {
        target[offset] = (byte) (value & 0xFF);
        target[offset + 1] = (byte) ((value >> 8) & 0xFF);
        target[offset + 2] = (byte) ((value >> 16) & 0xFF);
        target[offset + 3] = (byte) ((value >> 24) & 0xFF);
    }

    /** 往字节数组里写一个短整数（小端格式） */
    private static void writeShortLE(byte[] target, int offset, short value) {
        target[offset] = (byte) (value & 0xFF);
        target[offset + 1] = (byte) ((value >> 8) & 0xFF);
    }
}
