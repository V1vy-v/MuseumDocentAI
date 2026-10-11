package com.example.museumdocentai.model;

import java.util.List;

/**
 * 【A/B 共用】一条对话消息的数据结构。
 *
 * 这个类只描述"一条消息长什么样"，不放界面和网络逻辑：
 * - role：这条消息是用户发的（USER）还是 AI 回的（AI）
 * - text：消息文字
 * - sources：AI 回答附带的资料来源（界面上显示"来源：xxx"小字）
 * - status：消息状态——LOADING（等待回答）/ DONE（已完成）/ ERROR（出错）
 */
public class ChatMessage {

    /** 发言者：用户 / AI */
    public enum Role {
        USER,
        AI
    }

    /** 消息状态：加载中 / 已完成 / 出错 */
    public enum Status {
        LOADING,
        DONE,
        ERROR
    }

    /** 谁说的（创建后不变） */
    private final Role role;

    /** 消息文字（AI 回答回来后从"思考中…"替换成真实内容） */
    private String text;

    /** 资料来源列表，可以为空 */
    private List<String> sources;

    /** 当前状态 */
    private Status status;

    public ChatMessage(Role role, String text, List<String> sources, Status status) {
        this.role = role;
        this.text = text;
        this.sources = sources;
        this.status = status;
    }

    public Role getRole() {
        return role;
    }

    public String getText() {
        return text;
    }

    public void setText(String text) {
        this.text = text;
    }

    public List<String> getSources() {
        return sources;
    }

    public void setSources(List<String> sources) {
        this.sources = sources;
    }

    public Status getStatus() {
        return status;
    }

    public void setStatus(Status status) {
        this.status = status;
    }
}
