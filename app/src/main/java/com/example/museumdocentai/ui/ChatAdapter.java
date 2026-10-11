package com.example.museumdocentai.ui;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.example.museumdocentai.R;
import com.example.museumdocentai.model.ChatMessage;

import java.util.List;

/**
 * 【角色 A 负责】对话消息列表的适配器。
 *
 * 做什么：把 ChatMessage 数据"画"成界面上的一个个气泡——
 * - 用户的消息：靠右、深色气泡、白字；
 * - AI 的回答：靠左、浅色气泡、深字，气泡下方可显示"来源：xxx"小字；
 * - 状态为"加载中"：气泡里显示"思考中…"；
 * - 状态为"出错"：气泡里红字显示错误说明。
 *
 * RecyclerView 是安卓的"长列表"控件：屏幕外的气泡会被回收复用，所以每条数据
 * 绑定时都要把颜色、文字、对齐方式重新设置一遍。
 */
public class ChatAdapter extends RecyclerView.Adapter<ChatAdapter.MessageViewHolder> {

    private final Context context;

    /** 消息数据（和界面管理器共用同一个列表，改完调 refresh() 刷新） */
    private final List<ChatMessage> messages;

    public ChatAdapter(Context context, List<ChatMessage> messages) {
        this.context = context;
        this.messages = messages;
    }

    /** 一个气泡条目里包含的控件 */
    static class MessageViewHolder extends RecyclerView.ViewHolder {
        final LinearLayout root;
        final TextView bubble;
        final TextView sources;

        MessageViewHolder(View itemView) {
            super(itemView);
            root = itemView.findViewById(R.id.layout_bubble_item);
            bubble = itemView.findViewById(R.id.text_bubble);
            sources = itemView.findViewById(R.id.text_sources);
        }
    }

    @NonNull
    @Override
    public MessageViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_chat_message, parent, false);
        return new MessageViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull MessageViewHolder holder, int position) {
        ChatMessage message = messages.get(position);
        boolean isUser = message.getRole() == ChatMessage.Role.USER;

        // 对齐方式：用户靠右、AI 靠左
        holder.root.setGravity(isUser ? Gravity.END : Gravity.START);

        // 画气泡背景（圆角）：用户深色、AI 浅色
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(16));
        if (isUser) {
            background.setColor(Color.parseColor("#1F5FA8"));
            holder.bubble.setTextColor(Color.WHITE);
        } else {
            background.setColor(Color.parseColor("#EDEFF2"));
            holder.bubble.setTextColor(Color.parseColor("#212121"));
        }
        holder.bubble.setBackground(background);

        // 气泡文字：按消息状态显示
        if (message.getStatus() == ChatMessage.Status.LOADING) {
            // 还在等后端回答：显示"思考中…"
            holder.bubble.setText(context.getString(R.string.status_thinking));
            holder.bubble.setAlpha(0.6f);
        } else {
            holder.bubble.setText(message.getText());
            holder.bubble.setAlpha(1f);
            if (message.getStatus() == ChatMessage.Status.ERROR) {
                // 出错：红字提示
                holder.bubble.setTextColor(Color.parseColor("#B00020"));
            }
        }

        // 资料来源小字：只有 AI 回答且带来源时显示
        List<String> sources = message.getSources();
        if (!isUser && sources != null && !sources.isEmpty()) {
            holder.sources.setText(context.getString(
                    R.string.source_label, TextUtils.join("、", sources)));
            holder.sources.setVisibility(View.VISIBLE);
        } else {
            holder.sources.setVisibility(View.GONE);
        }
    }

    @Override
    public int getItemCount() {
        return messages.size();
    }

    /** 加一条新消息到列表末尾（比整体刷新更高效） */
    public void add(ChatMessage message) {
        messages.add(message);
        notifyItemInserted(messages.size() - 1);
    }

    /** 第 position 条消息内容变了，只刷新那一条 */
    public void update(int position) {
        notifyItemChanged(position);
    }

    /** 把 dp（布局单位）换算成像素，圆角用 */
    private int dp(int value) {
        return (int) (value * context.getResources().getDisplayMetrics().density + 0.5f);
    }
}
