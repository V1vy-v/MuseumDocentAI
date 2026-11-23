"""检索评测：关键词 vs 向量（30 题）

题目不是手写挑的，而是从知识库里自动取样，避免"专挑有利样本"：
  · 20 道文物题（取 20 件不同博物馆的文物卡，问年代/类别）
  · 6 道馆级信息题（问开放时间，期望命中该馆）
  · 4 道无关/闲聊题（期望不返回任何资料）

判定：
  · 首条命中：第 1 条来源包含期望实体
  · 任一命中：前 3 条来源里有期望实体
  · 无关题：返回 0 条 = 正确（否则算误召回）
"""
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests  # noqa: E402

B = "http://127.0.0.1:8000"

# 路径都相对脚本自身推导，换机器/换目录都能跑（原来写死了开发机的绝对路径）
_BACKEND = Path(__file__).resolve().parents[1]
KB = _BACKEND / "knowledge_base" / "全国博物馆资料馆"
OUT_JSON = _BACKEND / "data" / "eval_data.json"      # data/ 已在 .gitignore 里


def sample_artifacts(n=20):
    """按馆名排序后等距取样，保证覆盖不同博物馆"""
    cards = sorted((KB / "artifacts").rglob("*.md"), key=lambda p: (p.parent.name, p.stem))
    if not cards:
        return []
    step = max(1, len(cards) // n)
    picked = cards[::step][:n]
    return [(p.stem, p.parent.name) for p in picked]


def sample_museums(n=6):
    """挑有"参观信息"小节的馆，问开放时间"""
    out = []
    for p in sorted((KB / "museums").rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "开放时间" in text:
            out.append(p.stem)
        if len(out) >= n:
            break
    return out


def build_cases():
    cases = []
    for i, (title, museum) in enumerate(sample_artifacts()):
        if i % 2 == 0:
            cases.append({"kind": "文物·年代", "q": f"《{title}》是什么年代的文物？", "expect": [title]})
        else:
            cases.append({"kind": "文物·类别", "q": f"《{title}》属于什么类别？", "expect": [title]})
    for museum in sample_museums():
        cases.append({"kind": "馆级信息", "q": f"{museum}的开放时间是几点", "expect": [museum]})
    for q in ["附近有什么好吃的", "今天天气怎么样", "帮我写一首关于春天的诗", "推荐一部最近好看的电影"]:
        cases.append({"kind": "无关/闲聊", "q": q, "expect": []})
    return cases


def ask(q, mode, sid, retries=3):
    last = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.post(B + "/api/chat", timeout=240,
                              json={"question": q, "session_id": sid, "retrieval": mode})
            data = r.json()
            time.sleep(0.35)                     # 别把 embedding 接口打太密
            return data.get("sources") or [], round(time.time() - t0, 2)
        except Exception as exc:                  # noqa: BLE001 —— 网络抖动就重试
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


def judge(case, sources):
    expect = case["expect"]
    if not expect:
        return (len(sources) == 0), (sources[0] if sources else "")
    top_ok = bool(sources) and any(e in sources[0] for e in expect)
    any_ok = any(any(e in s for e in expect) for s in sources)
    return top_ok, (sources[0] if sources else ""), any_ok


def main():
    cases = build_cases()
    rows = []
    for idx, case in enumerate(cases):
        sid = f"eval-{idx}"
        kw_src, kw_t = ask(case["q"], "keyword", sid + "-kw")
        vec_src, vec_t = ask(case["q"], "vector", sid + "-vec")

        kw_top, kw_first = judge(case, kw_src)[0], judge(case, kw_src)[1]
        kw_any = len(case["expect"]) == 0 and kw_top or (
            any(any(e in s for e in case["expect"]) for s in kw_src) if case["expect"] else kw_top)
        vec_top, vec_first = judge(case, vec_src)[0], judge(case, vec_src)[1]
        vec_any = len(case["expect"]) == 0 and vec_top or (
            any(any(e in s for e in case["expect"]) for s in vec_src) if case["expect"] else vec_top)

        rows.append({
            "kind": case["kind"], "q": case["q"], "expect": case["expect"],
            "kw_sources": kw_src, "kw_top": kw_top, "kw_any": bool(kw_any), "kw_time": kw_t,
            "vec_sources": vec_src, "vec_top": vec_top, "vec_any": bool(vec_any), "vec_time": vec_t,
        })
        print(f"{idx + 1:02d}/{len(cases)} {case['kind']:6s} {case['q'][:26]:28s} "
              f"关键词{'✓' if kw_top else '✗'} 向量{'✓' if vec_top else '✗'}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def rate(key):
        return sum(1 for r in rows if r[key]), len(rows)

    print("\n=== 汇总 ===")
    for key, name in (("kw_top", "关键词·首条命中"), ("vec_top", "向量·首条命中"),
                      ("kw_any", "关键词·任一命中"), ("vec_any", "向量·任一命中")):
        hit, total = rate(key)
        print(f"{name}: {hit}/{total} = {hit / total * 100:.0f}%")
    kw_avg = sum(r["kw_time"] for r in rows) / len(rows)
    vec_avg = sum(r["vec_time"] for r in rows) / len(rows)
    print(f"平均耗时: 关键词 {kw_avg:.2f}s / 向量 {vec_avg:.2f}s")

    # 分类统计
    print("\n=== 分类首条命中 ===")
    for kind in ("文物·年代", "文物·类别", "馆级信息", "无关/闲聊"):
        sub = [r for r in rows if r["kind"] == kind]
        if sub:
            k = sum(1 for r in sub if r["kw_top"])
            v = sum(1 for r in sub if r["vec_top"])
            print(f"{kind}: 关键词 {k}/{len(sub)}，向量 {v}/{len(sub)}")


if __name__ == "__main__":
    main()
