package com.example.museumdocentai.model;

import org.json.JSONObject;

/**
 * 【角色 A 负责】资料库里的一份资料（只用于手动检索页面）。
 *
 * 与 ChatMessage 的区别：ChatMessage 是"对话气泡"，这个是"资料条目"，
 * 点开能看到原文。
 */
public class KbItem {

    /** 文档标题（文物名 / 博物馆名） */
    public final String title;
    /** 相对 knowledge_base 的路径，点开详情时原样传给后端 */
    public final String path;
    /** "museum" 或 "artifact" */
    public final String kind;
    /** 省份 / 所在地 */
    public final String province;
    /** 所属博物馆（文物卡是收藏单位，博物馆卡就是自己） */
    public final String museum;
    /** 文物类别（青铜器/书画/陶瓷…），博物馆卡为空 */
    public final String category;
    /** 列表里显示的一小段摘要 */
    public final String snippet;

    public KbItem(String title, String path, String kind, String province,
                  String museum, String category, String snippet) {
        this.title = title;
        this.path = path;
        this.kind = kind;
        this.province = province;
        this.museum = museum;
        this.category = category;
        this.snippet = snippet;
    }

    /** 后端返回的一行 JSON → 条目 */
    public static KbItem from(JSONObject json) {
        return new KbItem(
                json.optString("title", ""),
                json.optString("path", ""),
                json.optString("kind", ""),
                json.optString("province", ""),
                json.optString("museum", ""),
                json.optString("category", ""),
                json.optString("snippet", ""));
    }

    public boolean isArtifact() {
        return "artifact".equals(kind);
    }

    /** 列表里的第二行："文物 · 湖北省 · 湖北省博物馆 · 青铜器" */
    public String metaLine() {
        StringBuilder sb = new StringBuilder(isArtifact() ? "文物" : "博物馆");
        if (!province.isEmpty()) {
            sb.append(" · ").append(province);
        }
        if (isArtifact() && !museum.isEmpty()) {
            sb.append(" · ").append(museum);
        }
        if (!category.isEmpty()) {
            sb.append(" · ").append(category);
        }
        return sb.toString();
    }
}
