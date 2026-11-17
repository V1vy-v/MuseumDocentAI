package com.example.museumdocentai;

import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.model.FilterItem;
import com.example.museumdocentai.model.KbItem;
import com.example.museumdocentai.net.ApiClient;
import com.example.museumdocentai.net.ChatApi;
import com.example.museumdocentai.ui.KbAdapter;

import org.json.JSONArray;
import org.json.JSONException;

import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】资料库页面：不经过 AI，直接按关键词翻资料原文。
 *
 * 相比"只能搜一下"的初版，这里补齐了资料库该有的东西：
 * 1. 三级筛选：资料类型（全部/博物馆/文物）+ 地区（31 省）+ 文物类别（青铜器/书画…）；
 * 2. 分页加载：一次 20 条，滚到底自动加载下一页；
 * 3. 搜索历史：最近 10 个关键词做成小按钮，点一下直接重搜。
 *
 * 为什么单独做这个页面：模型不可用时照样能查；演示时能拿出资料原文证明回答有出处。
 */
public class BrowseActivity extends AppCompatActivity {

    private static final int PAGE_SIZE = 20;
    private static final String PREFS = "docent_prefs";
    private static final String KEY_HISTORY = "kb_search_history";
    private static final int HISTORY_MAX = 10;

    private ApiClient api;
    private KbAdapter adapter;
    private EditText editSearch;
    private TextView textStatus;
    private TextView textCount;
    private LinearLayout layoutHistory;
    private HorizontalScrollView scrollHistory;
    private Spinner spinnerProvince;
    private Spinner spinnerCategory;

    /** 当前筛选条件 */
    private String kind = "";
    private String province = "";
    private String category = "";

    /** 分页状态 */
    private int total = 0;
    private boolean loading = false;
    private boolean hasMore = false;

    /** 下拉框数据（第 0 项固定是"全部"） */
    private final List<FilterItem> provinceOptions = new ArrayList<>();
    private final List<FilterItem> categoryOptions = new ArrayList<>();
    /** 初始化下拉框时会触发 onItemSelected，用这个标记跳过 */
    private boolean bindingSpinners = false;

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
        layoutHistory = findViewById(R.id.layout_history);
        scrollHistory = findViewById(R.id.scroll_history);
        spinnerProvince = findViewById(R.id.spinner_province);
        spinnerCategory = findViewById(R.id.spinner_category);

        RecyclerView recycler = findViewById(R.id.recycler_docs);
        LinearLayoutManager layoutManager = new LinearLayoutManager(this);
        recycler.setLayoutManager(layoutManager);
        adapter = new KbAdapter(this::openDoc);
        recycler.setAdapter(adapter);

        // 滚到底部自动加载下一页
        recycler.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull RecyclerView rv, int dx, int dy) {
                if (dy <= 0 || loading || !hasMore) {
                    return;
                }
                int lastVisible = layoutManager.findLastVisibleItemPosition();
                if (lastVisible >= adapter.size() - 3) {
                    loadPage(adapter.size());
                }
            }
        });

        findViewById(R.id.btn_back).setOnClickListener(v -> finish());
        findViewById(R.id.btn_search).setOnClickListener(v -> {
            hideKeyboard();
            doSearch();
        });
        editSearch.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                hideKeyboard();
                doSearch();
                return true;
            }
            return false;
        });

        findViewById(R.id.btn_kind_all).setOnClickListener(v -> {
            kind = "";
            doSearch();
        });
        findViewById(R.id.btn_kind_museum).setOnClickListener(v -> {
            kind = "museum";
            doSearch();
        });
        findViewById(R.id.btn_kind_artifact).setOnClickListener(v -> {
            kind = "artifact";
            doSearch();
        });

        spinnerProvince.setOnItemSelectedListener(new SimpleSelectListener() {
            @Override
            public void onSelected(int position) {
                // Spinner 的选中回调是异步派发的，重建选项时也会触发。
                // 值没变就直接返回，否则会和"重建选项"互相触发，疯狂重复检索。
                String next = position == 0 ? "" : provinceOptions.get(position).name;
                if (next.equals(province)) {
                    return;
                }
                province = next;
                doSearch();
            }
        });
        spinnerCategory.setOnItemSelectedListener(new SimpleSelectListener() {
            @Override
            public void onSelected(int position) {
                String next = position == 0 ? "" : categoryOptions.get(position).name;
                if (next.equals(category)) {
                    return;
                }
                category = next;
                doSearch();
            }
        });

        renderHistory();
        doSearch();
    }

    // ================== 检索 ==================

    /** 重新检索（条件变了就从头查第一页） */
    private void doSearch() {
        final String query = editSearch.getText().toString().trim();
        if (!query.isEmpty()) {
            rememberQuery(query);
        }
        loading = true;
        showStatus(getString(R.string.browse_loading));
        api.searchKb(query, kind, province, category, PAGE_SIZE, 0, new ChatApi.KbListCallback() {
            @Override
            public void onList(List<KbItem> items, int totalCount,
                               List<FilterItem> provinces, List<FilterItem> categories) {
                loading = false;
                adapter.submit(items);
                total = totalCount;
                hasMore = adapter.size() < total;
                textCount.setText(getString(R.string.browse_count, total));
                bindFilterOptions(provinces, categories);
                if (items.isEmpty()) {
                    showStatus(getString(R.string.browse_empty));
                } else {
                    hideStatus();
                }
            }

            @Override
            public void onFailure(String message) {
                loading = false;
                showStatus(message);
                textCount.setText("");
            }
        });
    }

    /** 加载下一页 */
    private void loadPage(int offset) {
        if (loading) {
            return;
        }
        loading = true;
        String query = editSearch.getText().toString().trim();
        api.searchKb(query, kind, province, category, PAGE_SIZE, offset, new ChatApi.KbListCallback() {
            @Override
            public void onList(List<KbItem> items, int totalCount,
                               List<FilterItem> provinces, List<FilterItem> categories) {
                loading = false;
                adapter.append(items);
                total = totalCount;
                hasMore = adapter.size() < total;
                textCount.setText(getString(R.string.browse_count, total));
            }

            @Override
            public void onFailure(String message) {
                loading = false;
                showStatus(message);
            }
        });
    }

    // ================== 下拉筛选 ==================

    private void bindFilterOptions(List<FilterItem> provinces, List<FilterItem> categories) {
        // 只重建选项、不打断当前选择（重建时用 bindingSpinners 屏蔽回调）
        bindingSpinners = true;

        provinceOptions.clear();
        provinceOptions.add(new FilterItem(getString(R.string.browse_kind_all), 0));
        provinceOptions.addAll(provinces);
        bindSpinner(spinnerProvince, provinceOptions, province);

        categoryOptions.clear();
        categoryOptions.add(new FilterItem(getString(R.string.browse_kind_all), 0));
        categoryOptions.addAll(categories);
        bindSpinner(spinnerCategory, categoryOptions, category);

        bindingSpinners = false;
    }

    private void bindSpinner(Spinner spinner, List<FilterItem> options, String selected) {
        List<String> labels = new ArrayList<>();
        int selectIndex = 0;
        for (int i = 0; i < options.size(); i++) {
            labels.add(options.get(i).label());
            if (!selected.isEmpty() && options.get(i).name.equals(selected)) {
                selectIndex = i;
            }
        }
        ArrayAdapter<String> arrayAdapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, labels);
        arrayAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(arrayAdapter);
        spinner.setSelection(selectIndex, false);
    }

    // ================== 搜索历史 ==================

    private void rememberQuery(String query) {
        List<String> history = loadHistory();
        history.remove(query);
        history.add(0, query);
        while (history.size() > HISTORY_MAX) {
            history.remove(history.size() - 1);
        }
        saveHistory(history);
        renderHistory();
    }

    private void renderHistory() {
        List<String> history = loadHistory();
        layoutHistory.removeAllViews();
        scrollHistory.setVisibility(history.isEmpty() ? View.GONE : View.VISIBLE);
        for (String word : history) {
            TextView chip = new TextView(this);
            chip.setText(word);
            chip.setTextSize(12);
            chip.setPadding(24, 8, 24, 8);
            chip.setBackgroundColor(0xFFEEEBF5);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lp.setMargins(0, 0, 12, 0);
            chip.setLayoutParams(lp);
            chip.setOnClickListener(v -> {
                editSearch.setText(word);
                editSearch.setSelection(word.length());
                doSearch();
            });
            layoutHistory.addView(chip);
        }
    }

    private List<String> loadHistory() {
        List<String> list = new ArrayList<>();
        SharedPreferences prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String raw = prefs.getString(KEY_HISTORY, "");
        if (raw == null || raw.isEmpty()) {
            return list;
        }
        try {
            JSONArray array = new JSONArray(raw);
            for (int i = 0; i < array.length(); i++) {
                String one = array.optString(i, "");
                if (!one.isEmpty()) {
                    list.add(one);
                }
            }
        } catch (JSONException ignored) {
            // 存坏了就当没有，不影响使用
        }
        return list;
    }

    private void saveHistory(List<String> history) {
        JSONArray array = new JSONArray();
        for (String one : history) {
            array.put(one);
        }
        getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putString(KEY_HISTORY, array.toString()).apply();
    }

    // ================== 详情与提示 ==================

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

    private void hideKeyboard() {
        InputMethodManager manager = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (manager != null) {
            manager.hideSoftInputFromWindow(editSearch.getWindowToken(), 0);
        }
    }

    /** Spinner 的选中回调默认实现（只要 onSelected 一个方法，少写样板代码） */
    private abstract static class SimpleSelectListener implements AdapterView.OnItemSelectedListener {
        @Override
        public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
            onSelected(position);
        }

        @Override
        public void onNothingSelected(AdapterView<?> parent) {
        }

        abstract void onSelected(int position);
    }
}
