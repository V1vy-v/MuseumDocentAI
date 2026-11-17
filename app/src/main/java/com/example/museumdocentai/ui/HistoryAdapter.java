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
 * 【角色 A 负责】历史对话列表适配器。
 */
public class HistoryAdapter extends RecyclerView.Adapter<HistoryAdapter.Holder> {

    public interface OnItemClick {
        void onClick(SessionInfo info);
    }

    private final List<SessionInfo> items = new ArrayList<>();
    private final OnItemClick onItemClick;

    public HistoryAdapter(OnItemClick onItemClick) {
        this.onItemClick = onItemClick;
    }

    public void submit(List<SessionInfo> list) {
        items.clear();
        if (list != null) {
            items.addAll(list);
        }
        notifyDataSetChanged();
    }

    public int size() {
        return items.size();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_history, parent, false);
        return new Holder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        SessionInfo info = items.get(position);
        holder.title.setText(info.title.isEmpty() ? "（无标题对话）" : info.title);
        holder.meta.setText(info.metaLine());
        holder.itemView.setOnClickListener(v -> {
            if (onItemClick != null) {
                onItemClick.onClick(info);
            }
        });
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class Holder extends RecyclerView.ViewHolder {
        final TextView title;
        final TextView meta;

        Holder(@NonNull View itemView) {
            super(itemView);
            title = itemView.findViewById(R.id.text_history_title);
            meta = itemView.findViewById(R.id.text_history_meta);
        }
    }
}
