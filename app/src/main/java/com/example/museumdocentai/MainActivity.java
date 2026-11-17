package com.example.museumdocentai;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.EditText;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.model.SessionInfo;
import com.example.museumdocentai.net.ApiClient;
import com.example.museumdocentai.net.ChatApi;
import com.example.museumdocentai.ui.ChatUiManager;
import com.example.museumdocentai.ui.HistoryAdapter;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * 【角色 A 负责】页面入口：组装界面、转发事件、管理左侧历史抽屉。
 *
 * 布局参考 DeepSeek 手机端：白底极简顶栏（☰ / 标题 / ✎），
 * 历史对话收进左侧抽屉，按"今天 / 7 天内 / 30 天内"分组。
 */
public class MainActivity extends AppCompatActivity {

    private static final int REQUEST_RECORD_AUDIO = 1001;

    private ChatUiManager uiManager;
    private String sessionId;
    private ApiClient api;

    private View drawer;
    private View scrim;
    private HistoryAdapter historyAdapter;
    private EditText editHistorySearch;

    /** 后端返回的全部会话（搜索时在本地过滤） */
    private final List<SessionInfo> allSessions = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        sessionId = UUID.randomUUID().toString();
        uiManager = new ChatUiManager(this, sessionId);
        api = new ApiClient(this);

        // 输入区
        findViewById(R.id.btn_send).setOnClickListener(v -> uiManager.onSendClicked());
        findViewById(R.id.btn_mic).setOnClickListener(v -> onMicClicked());
        findViewById(R.id.btn_browse).setOnClickListener(v ->
                startActivity(new Intent(this, BrowseActivity.class)));
        findViewById(R.id.btn_voice).setOnClickListener(v -> uiManager.toggleVoiceReply());

        // 顶栏
        findViewById(R.id.btn_drawer).setOnClickListener(v -> openDrawer());
        findViewById(R.id.btn_new_chat).setOnClickListener(v -> startNewSession());
        findViewById(R.id.btn_settings).setOnClickListener(v -> uiManager.showServerDialog());

        // 抽屉
        drawer = findViewById(R.id.drawer);
        scrim = findViewById(R.id.scrim);
        scrim.setOnClickListener(v -> closeDrawer());

        editHistorySearch = findViewById(R.id.edit_history_search);
        editHistorySearch.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                renderHistory(s.toString().trim());
            }
        });

        RecyclerView recycler = findViewById(R.id.recycler_history);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        historyAdapter = new HistoryAdapter(info -> {
            closeDrawer();
            sessionId = info.sessionId;
            uiManager.loadHistorySession(sessionId);
        });
        recycler.setAdapter(historyAdapter);

        setupBackHandler();
    }

    // ================== 历史抽屉 ==================

    private void openDrawer() {
        drawer.setVisibility(View.VISIBLE);
        scrim.setVisibility(View.VISIBLE);
        loadSessions();
    }

    private void closeDrawer() {
        drawer.setVisibility(View.GONE);
        scrim.setVisibility(View.GONE);
    }

    private void loadSessions() {
        api.listSessions(50, new ChatApi.SessionListCallback() {
            @Override
            public void onList(List<SessionInfo> sessions) {
                allSessions.clear();
                allSessions.addAll(sessions);
                renderHistory(editHistorySearch.getText().toString().trim());
            }

            @Override
            public void onFailure(String message) {
                Toast.makeText(MainActivity.this, message, Toast.LENGTH_SHORT).show();
            }
        });
    }

    /** 按关键词过滤 + 按时间分组（今天 / 7 天内 / 30 天内 / 更早） */
    private void renderHistory(String keyword) {
        Map<String, List<SessionInfo>> groups = new LinkedHashMap<>();
        String[] order = {
                getString(R.string.history_group_today),
                getString(R.string.history_group_week),
                getString(R.string.history_group_month),
                getString(R.string.history_group_older),
        };
        for (String key : order) {
            groups.put(key, new ArrayList<>());
        }
        for (SessionInfo info : allSessions) {
            if (!keyword.isEmpty() && !info.title.contains(keyword)) {
                continue;
            }
            groups.get(groupOf(info.updatedAt)).add(info);
        }

        List<Object> rows = new ArrayList<>();
        for (String key : order) {
            List<SessionInfo> list = groups.get(key);
            if (list == null || list.isEmpty()) {
                continue;
            }
            rows.add(key);
            rows.addAll(list);
        }
        historyAdapter.submit(rows);
    }

    private String groupOf(String updatedAt) {
        try {
            SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);
            format.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
            Date date = format.parse(updatedAt);
            if (date == null) {
                return getString(R.string.history_group_older);
            }
            long days = (System.currentTimeMillis() - date.getTime()) / 86400000L;
            if (days <= 0) {
                return getString(R.string.history_group_today);
            }
            if (days < 7) {
                return getString(R.string.history_group_week);
            }
            if (days < 30) {
                return getString(R.string.history_group_month);
            }
            return getString(R.string.history_group_older);
        } catch (Exception e) {
            return getString(R.string.history_group_older);
        }
    }

    private void startNewSession() {
        closeDrawer();
        sessionId = UUID.randomUUID().toString();
        uiManager.startNewSession(sessionId);
        // 界面本来就是空的时候，清空看不出变化，给个明确反馈
        Toast.makeText(this, R.string.toast_new_chat, Toast.LENGTH_SHORT).show();
    }

    /** 点麦克风按钮：有录音权限就直接录，没有就先申请 */
    private void onMicClicked() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED) {
            uiManager.onMicClicked();
        } else {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.RECORD_AUDIO},
                    REQUEST_RECORD_AUDIO);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (granted) {
                uiManager.onMicClicked();
            } else {
                uiManager.onAudioPermissionDenied();
            }
        }
    }

    /** 返回键：抽屉开着先关抽屉，否则交给系统 */
    private void setupBackHandler() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (drawer.getVisibility() == View.VISIBLE) {
                    closeDrawer();
                    return;
                }
                setEnabled(false);
                getOnBackPressedDispatcher().onBackPressed();
            }
        });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        uiManager.release();
    }
}
