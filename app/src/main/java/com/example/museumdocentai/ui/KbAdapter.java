package com.example.museumdocentai.ui;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.R;
import com.example.museumdocentai.model.KbItem;

import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】资料库列表的适配器：一条资料一行（标题 / 类型·省份 / 摘要）。
 */
public class KbAdapter extends RecyclerView.Adapter<KbAdapter.Holder> {

    /** 点了某一条资料 */
    public interface OnItemClick {
        void onClick(KbItem item);
    }

    private final List<KbItem> items = new ArrayList<>();
    private final OnItemClick onItemClick;

    public KbAdapter(OnItemClick onItemClick) {
        this.onItemClick = onItemClick;
    }

    public void submit(List<KbItem> list) {
        items.clear();
        if (list != null) {
            items.addAll(list);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_kb_doc, parent, false);
        return new Holder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        KbItem item = items.get(position);
        holder.title.setText(item.title);
        holder.meta.setText(item.metaLine());
        holder.snippet.setText(item.snippet);
        holder.itemView.setOnClickListener(v -> {
            if (onItemClick != null) {
                onItemClick.onClick(item);
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
        final TextView snippet;

        Holder(@NonNull View itemView) {
            super(itemView);
            title = itemView.findViewById(R.id.text_doc_title);
            meta = itemView.findViewById(R.id.text_doc_meta);
            snippet = itemView.findViewById(R.id.text_doc_snippet);
        }
    }
}
