package com.example.museumdocentai.audio;

/**
 * 【角色 B 负责】语音播报与播放（占位骨架）
 *
 * 两种播报方式（二选一，取决于 mimo-v2.5-asr 是否支持语音输出）：
 * 1. 播放后端生成的音频文件（后端用 TTS API 合成）；
 * 2. 用手机自带的朗读功能（TextToSpeech）直接读回答文本。
 *
 * 其他职责：
 * - 音频焦点：来电话、其他 App 出声时自动暂停；
 * - 打断：用户开始新录音时立即停止播报（和 A 的界面联动）；
 * - 播放状态回传给界面：播放中 / 已结束。
 */
public class AudioPlayer {
    // TODO(角色B)：后续实现
}
