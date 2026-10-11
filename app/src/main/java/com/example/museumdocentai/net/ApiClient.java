package com.example.museumdocentai.net;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;

import com.example.museumdocentai.R;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 【角色 A 负责】网络请求客户端（实现 ChatApi 约定）。
 *
 * 职责：
 * 1. 统一配置后端服务地址（BASE_URL，改一处即可切换模拟器/真机）；
 * 2. 网络请求全部放后台线程执行（安卓不允许在主线程联网），结果用 Handler 切回主线程；
 * 3. 用系统自带的 HttpURLConnection 发请求、org.json 解析返回，不依赖第三方库；
 * 4. 出错时给界面一句友好的中文提示。
 */
public class ApiClient implements ChatApi {

    /**
     * 后端服务基地址：
     * - 模拟器访问电脑上的后端：http://10.0.2.2:8000（10.0.2.2 是模拟器里的"电脑"）
     * - 真机调试：改成电脑的局域网 IP，例如 http://192.168.1.10:8000
     */
    private static final String BASE_URL = "http://10.0.2.2:8000";

    /** 超时时间：连不上 10 秒算失败；等待回答最长 60 秒 */
    private static final int CONNECT_TIMEOUT_MS = 10000;
    private static final int READ_TIMEOUT_MS = 60000;

    private final Context context;

    /** 后台线程池：网络请求都在这里跑（单线程，排队执行） */
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    /** 主线程切换器：把后台拿到的结果送回界面 */
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    public ApiClient(Context context) {
        this.context = context.getApplicationContext();
    }

    // ======== 对外的两个请求（见 ChatApi 约定） ========

    @Override
    public void sendText(String question, String sessionId, Callback callback) {
        executor.execute(() -> {
            try {
                // 把问题组装成 JSON：{ "question": ..., "session_id": ... }
                JSONObject body = new JSONObject();
                body.put("question", question);
                body.put("session_id", sessionId);
                String responseText = postJson("/api/chat", body.toString());
                handleResponse(responseText, false, callback);
            } catch (IOException e) {
                deliverFailure(callback, context.getString(R.string.err_network));
            } catch (JSONException e) {
                deliverFailure(callback, context.getString(R.string.err_server));
            }
        });
    }

    @Override
    public void sendVoice(File audioFile, String sessionId, Callback callback) {
        executor.execute(() -> {
            try {
                // JSON 解析在 handleResponse 内部完成，这里只需处理网络异常
                String responseText = postMultipart("/api/voice", audioFile, sessionId);
                handleResponse(responseText, true, callback);
            } catch (IOException e) {
                deliverFailure(callback, context.getString(R.string.err_network));
            }
        });
    }

    // ======== 请求的发送细节 ========

    /** 打开一个到后端的连接（统一设置超时） */
    private HttpURLConnection openConnection(String path) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(BASE_URL + path).openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        return connection;
    }

    /** 发送普通 JSON 请求，返回后端的原始应答文本 */
    private String postJson(String path, String jsonBody) throws IOException {
        HttpURLConnection connection = openConnection(path);
        try {
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setDoOutput(true);
            OutputStream out = connection.getOutputStream();
            out.write(jsonBody.getBytes(StandardCharsets.UTF_8));
            out.close();
            return readResponse(connection);
        } finally {
            connection.disconnect();
        }
    }

    /**
     * 发送 multipart/form-data 请求（上传录音文件用）。
     * 格式说明：请求体由若干"部分"组成，每部分用分隔线隔开；
     * 这里放两个部分——文本字段 session_id、文件字段 audio。
     */
    private String postMultipart(String path, File audioFile, String sessionId) throws IOException {
        HttpURLConnection connection = openConnection(path);
        String boundary = "----MuseumDocentAI" + System.currentTimeMillis();
        try {
            connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            connection.setDoOutput(true);
            OutputStream out = connection.getOutputStream();

            // 第 1 部分：会话编号（普通文本字段）
            out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(("Content-Disposition: form-data; name=\"session_id\"\r\n\r\n")
                    .getBytes(StandardCharsets.UTF_8));
            out.write(sessionId.getBytes(StandardCharsets.UTF_8));
            out.write("\r\n".getBytes(StandardCharsets.UTF_8));

            // 第 2 部分：录音文件（audio 字段）
            out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(("Content-Disposition: form-data; name=\"audio\"; filename=\"record.wav\"\r\n")
                    .getBytes(StandardCharsets.UTF_8));
            out.write("Content-Type: audio/wav\r\n\r\n".getBytes(StandardCharsets.UTF_8));
            FileInputStream fileIn = new FileInputStream(audioFile);
            byte[] buffer = new byte[8192];
            int n;
            while ((n = fileIn.read(buffer)) != -1) {
                out.write(buffer, 0, n);
            }
            fileIn.close();
            out.write("\r\n".getBytes(StandardCharsets.UTF_8));

            // 结束标记
            out.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            out.close();
            return readResponse(connection);
        } finally {
            connection.disconnect();
        }
    }

    /** 读取后端应答（成功或出错的应答都读出来） */
    private String readResponse(HttpURLConnection connection) throws IOException {
        int code = connection.getResponseCode();
        InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (stream == null) {
            throw new IOException("empty response");
        }
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
        StringBuilder builder = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            builder.append(line);
        }
        reader.close();
        return builder.toString();
    }

    // ======== 应答的解析与回传 ========

    /** 解析后端 JSON 应答，转换成界面需要的三样东西：回答文字、来源、可选音频 */
    private void handleResponse(String responseText, boolean withAudio, Callback callback) {
        try {
            JSONObject json = new JSONObject(responseText);

            // 后端约定的出错格式：{ "error": ..., "hint": ... }
            if (json.has("error")) {
                String hint = json.optString("hint", "");
                String error = json.optString("error", "");
                String message = !hint.isEmpty() ? hint : error;
                deliverFailure(callback,
                        message.isEmpty() ? context.getString(R.string.err_server) : message);
                return;
            }

            String answer = json.optString("answer", "");
            List<String> sources = new ArrayList<>();
            JSONArray array = json.optJSONArray("sources");
            if (array != null) {
                for (int i = 0; i < array.length(); i++) {
                    String source = array.optString(i, "");
                    if (!source.isEmpty()) {
                        sources.add(source);
                    }
                }
            }

            // 语音问答才带音频：audio_base64 是一段声音的"编码文本"，解码还原成字节
            byte[] audio = null;
            if (withAudio) {
                String base64 = json.optString("audio_base64", "");
                if (!base64.isEmpty()) {
                    audio = Base64.decode(base64, Base64.DEFAULT);
                }
            }

            final String finalAnswer = answer;
            final List<String> finalSources = sources;
            final byte[] finalAudio = audio;
            mainHandler.post(() -> callback.onSuccess(finalAnswer, finalSources, finalAudio));
        } catch (JSONException e) {
            deliverFailure(callback, context.getString(R.string.err_server));
        }
    }

    /** 把错误信息切回主线程交给界面 */
    private void deliverFailure(Callback callback, String message) {
        mainHandler.post(() -> callback.onFailure(message));
    }
}
