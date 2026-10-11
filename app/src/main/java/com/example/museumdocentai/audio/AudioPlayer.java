package com.example.museumdocentai.audio;

import android.content.Context;
import android.media.MediaPlayer;

import com.example.museumdocentai.R;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * 【角色 B 负责】语音播报播放器。
 *
 * 做什么：把后端返回的"回答音频"播放出来（AI 说的话变成声音）。
 * 后端返回的是一段音频字节流（MP3 或 WAV），先写到缓存文件，再交给系统播放器播。
 *
 * 关键能力：
 * - 打断：正在播放时用户要说话（点录音按钮），调 stop() 立即停止；
 * - 回调：播放结束、播放失败都会通知界面；
 * - 释放：页面销毁时调 release()，不占用手机声音通道。
 */
public class AudioPlayer {

    /** 播放过程的回调（在主线程执行，可以直接更新界面） */
    public interface Listener {
        /** 播放自然结束 */
        void onPlaybackFinished();

        /** 播放失败，message 是可以直接显示的提示 */
        void onPlaybackFailed(String message);
    }

    private final Context context;

    /** 当前正在播放的播放器（没有播放时为 null） */
    private MediaPlayer currentPlayer;

    public AudioPlayer(Context context) {
        this.context = context.getApplicationContext();
    }

    /**
     * 播放一段音频数据。
     * 如果正在播别的会先停掉（这就是"打断"）；
     * audioData 为空就不播（后端没给音频时的正常情况）。
     */
    public void play(byte[] audioData, Listener listener) {
        stop();
        if (audioData == null || audioData.length == 0) {
            return;
        }
        try {
            File file = writeAudioFile(audioData);
            MediaPlayer player = new MediaPlayer();
            currentPlayer = player;
            player.setDataSource(file.getAbsolutePath());
            // 播放完成：释放播放器，通知界面
            player.setOnCompletionListener(mp -> {
                if (currentPlayer == mp) {
                    currentPlayer = null;
                }
                mp.release();
                listener.onPlaybackFinished();
            });
            // 播放出错：释放播放器，通知界面
            player.setOnErrorListener((mp, what, extra) -> {
                if (currentPlayer == mp) {
                    currentPlayer = null;
                }
                mp.release();
                listener.onPlaybackFailed(context.getString(R.string.toast_play_failed));
                return true;
            });
            // 准备好之后自动开始播
            player.setOnPreparedListener(MediaPlayer::start);
            player.prepareAsync();
        } catch (IOException e) {
            listener.onPlaybackFailed(context.getString(R.string.toast_play_failed));
        }
    }

    /** 立即停止播放（打断机制用），随时可调 */
    public void stop() {
        if (currentPlayer != null) {
            try {
                currentPlayer.stop();
            } catch (Exception ignored) {
                // 还没准备好就停止会报错，忽略即可
            }
            currentPlayer.release();
            currentPlayer = null;
        }
    }

    /** 当前是否正在播放（界面判断要不要打断时用） */
    public boolean isPlaying() {
        return currentPlayer != null && currentPlayer.isPlaying();
    }

    /** 页面销毁时调用，释放声音通道 */
    public void release() {
        stop();
    }

    /**
     * 把音频字节写到缓存文件。
     * 按开头几个字节猜格式：RIFF 开头是 WAV，否则按 MP3 处理（系统播放器能自动识别）。
     */
    private File writeAudioFile(byte[] audioData) throws IOException {
        boolean isWav = audioData.length > 4
                && audioData[0] == 'R' && audioData[1] == 'I'
                && audioData[2] == 'F' && audioData[3] == 'F';
        File file = new File(context.getCacheDir(),
                "tts_" + System.currentTimeMillis() + (isWav ? ".wav" : ".mp3"));
        FileOutputStream out = new FileOutputStream(file);
        out.write(audioData);
        out.close();
        return file;
    }
}
