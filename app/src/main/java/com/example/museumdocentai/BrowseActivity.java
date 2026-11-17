package com.example.museumdocentai;

import android.app.AlertDialog;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.model.KbItem;
import com.example.museumdocentai.net.ApiClient;
import com.example.museumdocentai.net.ChatApi;
import com.example.museumdocentai.ui.KbAdapter;

import java.util.List;

/**
 * 【角色 A 负责】资料库页面：不经过 AI，直接按关键词翻资料原文。
 *
 * 为什么单独做这个页面：
 * 1. 观众可能只想查"越王勾践剑在哪个馆"，不需要聊天；
 * 2. 模型不可用（没网/没额度）时，这个功能照样能用；
 * 3. 演示时能拿出资料原文，证明回答确实有出处。
 *
 * 交互：输入关键词 → 搜索（也可以不输入，直接按"博物馆/文物"浏览）
 *       → 点一条 → 弹窗看全文。
 */
public class BrowseActivity extends AppCompatActivity {

    /** 每页最多取多少条（资料总量不大，一次取够即可） */
    private static final int PAGE_LIMIT = 50;

    private ApiClient api;
    private KbAdapter adapter;
    private EditText editSearch;
    private TextView textStatus;
    private TextView textCount;

    /** 当前筛选：""=全部、"museum"=博物馆、"artifact"=文物 */
    private String kind = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_browse);

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.browse_root), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        api = new ApiClient(this);
        editSearch = findViewById(R.id.edit_search);
        textStatus = findViewById(R.id.text_status);
        textCount = findViewById(R.id.text_count);

        RecyclerView recycler = findViewById(R.id.recycler_docs);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        adapter = new KbAdapter(this::openDoc);
        recycler.setAdapter(adapter);

        findViewById(R.id.btn_back).setOnClickListener(v -> finish());
        findViewById(R.id.btn_search).setOnClickListener(v -> runSearch());

        // 键盘上的"搜索"键等同于点按钮
        editSearch.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                runSearch();
                return true;
            }
            return false;
        });

        findViewById(R.id.btn_kind_all).setOnClickListener(v -> changeKind(""));
        findViewById(R.id.btn_kind_museum).setOnClickListener(v -> changeKind("museum"));
        findViewById(R.id.btn_kind_artifact).setOnClickListener(v -> changeKind("artifact"));

        // 进页面先按"博物馆"浏览一遍，让用户看到这里确实有东西
        runSearch();
    }

    private void changeKind(String newKind) {
        kind = newKind;
        runSearch();
    }

    /** 发起检索：关键词为空时后端按类型列出（浏览模式） */
    private void runSearch() {
        String query = editSearch.getText().toString().trim();
        showStatus(getString(R.string.browse_loading));
        api.searchKb(query, kind, PAGE_LIMIT, new ChatApi.KbListCallback() {
            @Override
            public void onList(List<KbItem> items, int total) {
                adapter.submit(items);
                textCount.setText(getString(R.string.browse_count, total));
                if (items.isEmpty()) {
                    showStatus(getString(R.string.browse_empty));
                } else {
                    hideStatus();
                }
            }

            @Override
            public void onFailure(String message) {
                showStatus(message);
                textCount.setText("");
            }
        });
    }

    /** 点一条资料：拉原文，弹窗展示 */
    private void openDoc(KbItem item) {
        api.openKbDoc(item.path, new ChatApi.KbDocCallback() {
            @Override
            public void onDoc(String title, String meta, String text) {
                View view = getLayoutInflater().inflate(R.layout.dialog_kb_doc, null);
                ((TextView) view.findViewById(R.id.text_dialog_title)).setText(title);
                ((TextView) view.findViewById(R.id.text_dialog_meta)).setText(meta);
                ((TextView) view.findViewById(R.id.text_dialog_body)).setText(
                        TextUtils.isEmpty(text) ? getString(R.string.browse_empty) : text);
                new AlertDialog.Builder(BrowseActivity.this)
                        .setView(view)
                        .setPositiveButton(R.string.browse_close, null)
                        .show();
            }

            @Override
            public void onFailure(String message) {
                showStatus(message);
            }
        });
    }

    private void showStatus(String message) {
        textStatus.setText(message);
        textStatus.setVisibility(View.VISIBLE);
    }

    private void hideStatus() {
        textStatus.setVisibility(View.GONE);
    }
}
