package com.example.museumdocentai.ui;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.R;
import com.example.museumdocentai.model.SessionInfo;

import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】历史对话抽屉的适配器。
 *
 * 支持两种行：分组标题（"今天／7 天内…"）和会话行。
 */
public class HistoryAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {

    public interface OnItemClick {
        void onClick(SessionInfo info);
    }

    private static final int TYPE_HEADER = 0;
    private static final int TYPE_ITEM = 1;

    /** 标题用 String，会话用 SessionInfo */
    private final List<Object> rows = new ArrayList<>();
    private final OnItemClick onItemClick;

    public HistoryAdapter(OnItemClick onItemClick) {
        this.onItemClick = onItemClick;
    }

    public void submit(List<Object> list) {
        rows.clear();
        if (list != null) {
            rows.addAll(list);
        }
        notifyDataSetChanged();
    }

    public int size() {
        return rows.size();
    }

    @Override
    public int getItemViewType(int position) {
        return rows.get(position) instanceof String ? TYPE_HEADER : TYPE_ITEM;
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        if (viewType == TYPE_HEADER) {
            View view = LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_history_header, parent, false);
            return new HeaderHolder(view);
        }
        View view = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_history, parent, false);
        return new ItemHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        Object row = rows.get(position);
        if (holder instanceof HeaderHolder) {
            ((HeaderHolder) holder).text.setText(String.valueOf(row));
            return;
        }
        SessionInfo info = (SessionInfo) row;
        ItemHolder itemHolder = (ItemHolder) holder;
        itemHolder.title.setText(info.title.isEmpty() ? "（无标题对话）" : info.title);
        itemHolder.meta.setText(info.metaLine());
        itemHolder.itemView.setOnClickListener(v -> {
            if (onItemClick != null) {
                onItemClick.onClick(info);
            }
        });
    }

    @Override
    public int getItemCount() {
        return rows.size();
    }

    static class HeaderHolder extends RecyclerView.ViewHolder {
        final TextView text;

        HeaderHolder(@NonNull View itemView) {
            super(itemView);
            text = itemView.findViewById(R.id.text_group);
        }
    }

    static class ItemHolder extends RecyclerView.ViewHolder {
        final TextView title;
        final TextView meta;

        ItemHolder(@NonNull View itemView) {
            super(itemView);
            title = itemView.findViewById(R.id.text_history_title);
            meta = itemView.findViewById(R.id.text_history_meta);
        }
    }
}
