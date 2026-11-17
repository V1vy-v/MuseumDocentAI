package com.example.museumdocentai.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】历史会话（列表里的一行）。
 *
 * 后端 GET /api/sessions 返回：{sessions:[{session_id,title,updated_at,message_count}]}
 */
public class SessionInfo {

    public final String sessionId;
    /** 首问，列表里当标题用 */
    public final String title;
    /** 最近一次活动时间（UTC ISO8601，直接截前 16 位显示即可） */
    public final String updatedAt;
    public final int messageCount;

    public SessionInfo(String sessionId, String title, String updatedAt, int messageCount) {
        this.sessionId = sessionId;
        this.title = title;
        this.updatedAt = updatedAt;
        this.messageCount = messageCount;
    }

    public static List<SessionInfo> listFrom(JSONObject json) {
        List<SessionInfo> list = new ArrayList<>();
        JSONArray array = json.optJSONArray("sessions");
        if (array == null) {
            return list;
        }
        for (int i = 0; i < array.length(); i++) {
            JSONObject one = array.optJSONObject(i);
            if (one == null) {
                continue;
            }
            String id = one.optString("session_id", "");
            if (id.isEmpty()) {
                continue;
            }
            list.add(new SessionInfo(id,
                    one.optString("title", ""),
                    one.optString("updated_at", ""),
                    one.optInt("message_count", 0)));
        }
        return list;
    }

    /** 列表里的第二行："3 条消息 · 2026-11-17 17:30" */
    public String metaLine() {
        String time = updatedAt.length() >= 16 ? updatedAt.substring(0, 16).replace('T', ' ') : updatedAt;
        return messageCount + " 条消息 · " + time;
    }
}
