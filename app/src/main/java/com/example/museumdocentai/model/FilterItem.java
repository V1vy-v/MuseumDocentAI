package com.example.museumdocentai.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 【角色 A 负责】筛选维度的一项（省份 / 文物类别 + 数量）。
 *
 * 后端 /api/kb/search 的 facets 返回：[{"name":"湖北省","count":31}, ...]
 * 界面上就是下拉框里的"湖北省（31）"。
 */
public class FilterItem {

    public final String name;
    public final int count;

    public FilterItem(String name, int count) {
        this.name = name;
        this.count = count;
    }

    /** 下拉框里显示的文本；count<=0 时不显示数量 */
    public String label() {
        return count > 0 ? name + "（" + count + "）" : name;
    }

    public static List<FilterItem> listFrom(JSONArray array) {
        List<FilterItem> list = new ArrayList<>();
        if (array == null) {
            return list;
        }
        for (int i = 0; i < array.length(); i++) {
            JSONObject one = array.optJSONObject(i);
            if (one == null) {
                continue;
            }
            String name = one.optString("name", "");
            if (!name.isEmpty()) {
                list.add(new FilterItem(name, one.optInt("count", 0)));
            }
        }
        return list;
    }
}
