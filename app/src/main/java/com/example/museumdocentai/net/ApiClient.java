package com.example.museumdocentai.net;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;

import com.example.museumdocentai.R;
import com.example.museumdocentai.model.ChatMessage;
import com.example.museumdocentai.model.FilterItem;
import com.example.museumdocentai.model.KbItem;
import com.example.museumdocentai.model.SessionInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
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
     * 后端服务基地址候选（按顺序尝试，连上哪个用哪个，之后固定用它）：
     * 1. http://10.0.2.2:8000  —— 模拟器默认（10.0.2.2 是模拟器里的"电脑"）
     * 2. http://127.0.0.1:8000 —— 配合 adb reverse 端口转发使用
     *    （电脑开了 Clash 等代理软件时 10.0.2.2 会被拦，用这个地址最稳；
     *      先在电脑上执行一次：adb reverse tcp:8000 tcp:8000）
     * 3. 真机调试：把电脑局域网 IP 加进来，例如 http://192.168.1.10:8000
     */
    private static final String[] BASE_URLS = {
            "http://10.0.2.2:8000",
            "http://127.0.0.1:8000",
    };

    /** 记住第一个连通的地址，后续请求直接用它（也会被用户手填的地址覆盖） */
    private static volatile String workingBaseUrl = null;

    /** 本地设置文件名与键（保存用户手填的服务器地址与语音播报开关） */
    private static final String PREFS_NAME = "docent_prefs";
    private static final String KEY_SERVER_URL = "server_url";

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
        loadServerUrl();
    }

    // ======== 服务器地址设置（真机测试时填电脑的局域网 IP） ========

    @Override
    public void setServerUrl(String url) {
        String normalized = normalizeUrl(url);
        workingBaseUrl = normalized.isEmpty() ? null : normalized;
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit().putString(KEY_SERVER_URL, normalized).apply();
    }

    @Override
    public String getServerUrl() {
        String saved = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(KEY_SERVER_URL, "");
        return saved == null ? "" : saved;
    }

    /** 启动时读回上次保存的地址；没保存过就保持"自动尝试" */
    private void loadServerUrl() {
        String saved = getServerUrl();
        if (!saved.isEmpty()) {
            workingBaseUrl = saved;
        }
    }

    /** 把用户输入整理成标准地址：补 http://、去空格、去末尾斜杠；空串表示自动 */
    private static String normalizeUrl(String raw) {
        if (raw == null) {
            return "";
        }
        String url = raw.trim();
        if (url.isEmpty() || "自动".equals(url)) {
            return "";
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
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

    @Override
    public void synthesize(String text, TtsCallback callback) {
        executor.execute(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("text", text);
                String responseText = postJson("/api/tts", body.toString());
                JSONObject json = new JSONObject(responseText);
                if (json.has("error")) {
                    String hint = json.optString("hint", "");
                    deliverTtsFailure(callback, hint.isEmpty()
                            ? context.getString(R.string.toast_tts_failed) : hint);
                    return;
                }
                String base64 = json.optString("audio_base64", "");
                if (base64.isEmpty()) {
                    deliverTtsFailure(callback, context.getString(R.string.toast_tts_failed));
                    return;
                }
                final byte[] audio = Base64.decode(base64, Base64.DEFAULT);
                mainHandler.post(() -> callback.onAudio(audio));
            } catch (IOException e) {
                deliverTtsFailure(callback, context.getString(R.string.toast_tts_failed));
            } catch (JSONException e) {
                deliverTtsFailure(callback, context.getString(R.string.toast_tts_failed));
            }
        });
    }

    /** 把语音合成的失败切回主线程交给界面 */
    private void deliverTtsFailure(TtsCallback callback, String message) {
        mainHandler.post(() -> callback.onFailure(message));
    }

    // ======== 资料库：手动检索（不经过大模型，也不消耗 token） ========

    @Override
    public void searchKb(String query, String kind, String province, String category,
                         int limit, int offset, KbListCallback callback) {
        executor.execute(() -> {
            StringBuilder path = new StringBuilder("/api/kb/search?limit=").append(limit)
                    .append("&offset=").append(offset);
            if (query != null && !query.trim().isEmpty()) {
                path.append("&q=").append(encode(query.trim()));
            }
            if (kind != null && !kind.isEmpty()) {
                path.append("&kind=").append(encode(kind));
            }
            if (province != null && !province.isEmpty()) {
                path.append("&province=").append(encode(province));
            }
            if (category != null && !category.isEmpty()) {
                path.append("&category=").append(encode(category));
            }
            try {
                JSONObject json = new JSONObject(getJson(path.toString()));
                JSONArray array = json.optJSONArray("items");
                List<KbItem> items = new ArrayList<>();
                if (array != null) {
                    for (int i = 0; i < array.length(); i++) {
                        JSONObject one = array.optJSONObject(i);
                        if (one != null) {
                            items.add(KbItem.from(one));
                        }
                    }
                }
                // 筛选维度（省份/类别 + 数量）跟着返回，界面直接拿来渲染下拉框
                JSONObject facets = json.optJSONObject("facets");
                List<FilterItem> provinces = FilterItem.listFrom(
                        facets == null ? null : facets.optJSONArray("provinces"));
                List<FilterItem> categories = FilterItem.listFrom(
                        facets == null ? null : facets.optJSONArray("categories"));

                final List<KbItem> result = items;
                final int total = json.optInt("total", result.size());
                final List<FilterItem> finalProvinces = provinces;
                final List<FilterItem> finalCategories = categories;
                mainHandler.post(() -> callback.onList(result, total, finalProvinces, finalCategories));
            } catch (IOException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_network)));
            } catch (JSONException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_server)));
            }
        });
    }

    @Override
    public void openKbDoc(String path, KbDocCallback callback) {
        executor.execute(() -> {
            try {
                JSONObject json = new JSONObject(getJson("/api/kb/doc?path=" + encode(path)));
                final String title = json.optString("title", "");
                final String kind = json.optString("kind", "");
                final String province = json.optString("province", "");
                final String museum = json.optString("museum", "");
                final String category = json.optString("category", "");
                final String text = json.optString("text", "");

                List<String> images = new ArrayList<>();
                JSONArray imgArray = json.optJSONArray("images");
                if (imgArray != null) {
                    for (int i = 0; i < imgArray.length(); i++) {
                        String one = imgArray.optString(i, "");
                        if (!one.isEmpty()) {
                            images.add(one);
                        }
                    }
                }

                StringBuilder meta = new StringBuilder("artifact".equals(kind) ? "文物" : "博物馆");
                if (!province.isEmpty()) {
                    meta.append(" · ").append(province);
                }
                if ("artifact".equals(kind) && !museum.isEmpty()) {
                    meta.append(" · ").append(museum);
                }
                if (!category.isEmpty()) {
                    meta.append(" · ").append(category);
                }
                final String metaLine = meta.toString();
                final List<String> finalImages = images;
                mainHandler.post(() -> callback.onDoc(title, metaLine, text, finalImages));
            } catch (IOException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_network)));
            } catch (JSONException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_server)));
            }
        });
    }

    @Override
    public void fetchImage(String path, ImageCallback callback) {
        executor.execute(() -> {
            for (String base : baseUrlsToTry()) {
                try {
                    byte[] data = getBytesOnce(base, "/api/kb/image?path=" + encode(path));
                    final Bitmap bitmap = BitmapFactory.decodeByteArray(data, 0, data.length);
                    if (bitmap != null) {
                        workingBaseUrl = base;
                        mainHandler.post(() -> callback.onImage(bitmap));
                        return;
                    }
                } catch (IOException ignored) {
                    // 换下一个地址重试
                }
            }
            mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_network)));
        });
    }

    /** GET 二进制（图片用），连不上会换地址重试 */
    private byte[] getBytesOnce(String baseUrl, String path) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(baseUrl + path).openConnection();
        connection.setRequestMethod("GET");
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        try {
            if (connection.getResponseCode() >= 400) {
                throw new IOException("HTTP " + connection.getResponseCode());
            }
            try (InputStream in = connection.getInputStream();
                 ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = in.read(buffer)) > 0) {
                    out.write(buffer, 0, read);
                }
                return out.toByteArray();
            }
        } finally {
            connection.disconnect();
        }
    }

    // ======== 流式问答 + 会话历史 ========

    @Override
    public void streamText(String question, String sessionId, StreamCallback callback) {
        executor.execute(() -> {
            JSONObject body = new JSONObject();
            try {
                body.put("question", question);
                body.put("session_id", sessionId);
            } catch (JSONException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_server)));
                return;
            }
            IOException lastError = null;
            for (String base : baseUrlsToTry()) {
                try {
                    streamOnce(base, "/api/chat/stream", body.toString(), callback);
                    workingBaseUrl = base;
                    return;
                } catch (IOException e) {
                    lastError = e;
                }
            }
            String message = lastError == null ? context.getString(R.string.err_network)
                    : context.getString(R.string.err_network);
            mainHandler.post(() -> callback.onFailure(message));
        });
    }

    /** 读一整个 SSE 流：event: meta / delta / done / error */
    private void streamOnce(String baseUrl, String path, String jsonBody, StreamCallback callback)
            throws IOException {
        HttpURLConnection connection = openConnection(baseUrl, path);
        try {
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "text/event-stream");
            connection.setDoOutput(true);
            OutputStream out = connection.getOutputStream();
            out.write(jsonBody.getBytes(StandardCharsets.UTF_8));
            out.close();

            if (connection.getResponseCode() >= 400) {
                throw new IOException("HTTP " + connection.getResponseCode());
            }

            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8));
            String event = "";
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("event:")) {
                    event = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    dispatchSseEvent(event, line.substring(5).trim(), callback);
                }
            }
            reader.close();
        } finally {
            connection.disconnect();
        }
    }

    private void dispatchSseEvent(String event, String payload, StreamCallback callback) {
        try {
            JSONObject json = new JSONObject(payload);
            switch (event) {
                case "meta": {
                    List<String> sources = new ArrayList<>();
                    JSONArray array = json.optJSONArray("sources");
                    if (array != null) {
                        for (int i = 0; i < array.length(); i++) {
                            String one = array.optString(i, "");
                            if (!one.isEmpty()) {
                                sources.add(one);
                            }
                        }
                    }
                    mainHandler.post(() -> callback.onMeta(sources));
                    break;
                }
                case "delta": {
                    String text = json.optString("text", "");
                    mainHandler.post(() -> callback.onDelta(text));
                    break;
                }
                case "done": {
                    String answer = json.optString("answer", "");
                    mainHandler.post(() -> callback.onDone(answer));
                    break;
                }
                case "error": {
                    String error = json.optString("error", "");
                    mainHandler.post(() -> callback.onFailure(
                            error.isEmpty() ? context.getString(R.string.err_server) : error));
                    break;
                }
                default:
                    break;      // 未知事件忽略，保证向后兼容
            }
        } catch (JSONException ignored) {
            // 单条事件解析失败不影响整条流
        }
    }

    @Override
    public void listSessions(int limit, SessionListCallback callback) {
        executor.execute(() -> {
            try {
                JSONObject json = new JSONObject(getJson("/api/sessions?limit=" + limit));
                final List<SessionInfo> sessions = SessionInfo.listFrom(json);
                mainHandler.post(() -> callback.onList(sessions));
            } catch (IOException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_network)));
            } catch (JSONException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_server)));
            }
        });
    }

    @Override
    public void loadMessages(String sessionId, MessagesCallback callback) {
        executor.execute(() -> {
            try {
                JSONObject json = new JSONObject(
                        getJson("/api/sessions/" + encode(sessionId) + "/messages"));
                JSONArray array = json.optJSONArray("messages");
                List<ChatMessage> messages = new ArrayList<>();
                if (array != null) {
                    for (int i = 0; i < array.length(); i++) {
                        JSONObject one = array.optJSONObject(i);
                        if (one == null) {
                            continue;
                        }
                        String role = one.optString("role", "");
                        String content = one.optString("content", "");
                        List<String> sources = new ArrayList<>();
                        JSONArray src = one.optJSONArray("sources");
                        if (src != null) {
                            for (int k = 0; k < src.length(); k++) {
                                sources.add(src.optString(k, ""));
                            }
                        }
                        ChatMessage.Role messageRole = "user".equals(role)
                                ? ChatMessage.Role.USER : ChatMessage.Role.AI;
                        messages.add(new ChatMessage(messageRole, content, sources,
                                ChatMessage.Status.DONE));
                    }
                }
                final List<ChatMessage> result = messages;
                mainHandler.post(() -> callback.onMessages(result));
            } catch (IOException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_network)));
            } catch (JSONException e) {
                mainHandler.post(() -> callback.onFailure(context.getString(R.string.err_server)));
            }
        });
    }

    /** 查询参数里的中文必须编码，否则 URL 直接报错 */
    private static String encode(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            return value;       // UTF-8 一定存在，这里只是编译器的形式要求
        }
    }

    // ======== 请求的发送细节 ========
    /** 打开一个到后端的连接（统一设置超时） */
    private HttpURLConnection openConnection(String baseUrl, String path) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(baseUrl + path).openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        return connection;
    }

    /** 候选地址列表：已经连通过的排最前 */
    private static List<String> baseUrlsToTry() {
        List<String> list = new ArrayList<>();
        String working = workingBaseUrl;
        if (working != null) {
            list.add(working);
        }
        for (String base : BASE_URLS) {
            if (!base.equals(working)) {
                list.add(base);
            }
        }
        return list;
    }

    /** 发送普通 JSON 请求，返回后端的原始应答文本（连不上会自动换下一个地址重试） */
    private String postJson(String path, String jsonBody) throws IOException {
        IOException lastError = null;
        for (String base : baseUrlsToTry()) {
            try {
                String result = postJsonOnce(base, path, jsonBody);
                workingBaseUrl = base;
                return result;
            } catch (IOException e) {
                lastError = e;
            }
        }
        throw lastError;
    }

    /** 发送 GET 请求（资料库检索用），连不上会自动换下一个地址重试 */
    private String getJson(String path) throws IOException {
        IOException lastError = null;
        for (String base : baseUrlsToTry()) {
            try {
                String result = getJsonOnce(base, path);
                workingBaseUrl = base;
                return result;
            } catch (IOException e) {
                lastError = e;
            }
        }
        throw lastError;
    }

    private String getJsonOnce(String baseUrl, String path) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(baseUrl + path).openConnection();
        connection.setRequestMethod("GET");
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        try {
            return readResponse(connection);
        } finally {
            connection.disconnect();
        }
    }

    private String postJsonOnce(String baseUrl, String path, String jsonBody) throws IOException {
        HttpURLConnection connection = openConnection(baseUrl, path);
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
     * 发送 multipart/form-data 请求（上传录音文件用），连不上会自动换地址重试。
     * 格式说明：请求体由若干"部分"组成，每部分用分隔线隔开；
     * 这里放两个部分——文本字段 session_id、文件字段 audio。
     */
    private String postMultipart(String path, File audioFile, String sessionId) throws IOException {
        IOException lastError = null;
        for (String base : baseUrlsToTry()) {
            try {
                String result = postMultipartOnce(base, path, audioFile, sessionId);
                workingBaseUrl = base;
                return result;
            } catch (IOException e) {
                lastError = e;
            }
        }
        throw lastError;
    }

    private String postMultipartOnce(String baseUrl, String path, File audioFile, String sessionId) throws IOException {
        HttpURLConnection connection = openConnection(baseUrl, path);
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

            // 语音提问时后端会带回识别出的问句，界面拿它替换"🎤 语音提问"占位
            String recognized = withAudio ? json.optString("question", "") : "";

            final String finalAnswer = answer;
            final List<String> finalSources = sources;
            final byte[] finalAudio = audio;
            final String finalRecognized = recognized;
            mainHandler.post(() -> callback.onSuccess(
                    finalAnswer, finalSources, finalAudio, finalRecognized));
        } catch (JSONException e) {
            deliverFailure(callback, context.getString(R.string.err_server));
        }
    }

    /** 把错误信息切回主线程交给界面 */
    private void deliverFailure(Callback callback, String message) {
        mainHandler.post(() -> callback.onFailure(message));
    }
}
