"""合成数据上的评测：对照植入信号清单，计算找回率与假信号数。只在合成数据运行结束后执行。"""

from __future__ import annotations


def evaluate(manifest: list[dict], conclusions: list[dict]) -> dict:
    planted = [s for s in manifest if s["kind"] != "无关字段"]
    nulls = {s["exposure"] for s in manifest if s["kind"] == "无关字段"}
    meaningful = [c for c in conclusions if c["meaningful"]]
    tested = {(c["hypothesis"]["exposure"], c["hypothesis"]["outcome"]) for c in conclusions}
    rows = []
    for s in planted:
        hits = [c for c in meaningful if c["hypothesis"]["exposure"] == s["exposure"]
                and c["hypothesis"]["outcome"] == s["outcome"] and (c["result"]["estimate"] > 1) == (s["log_or"] > 0)]
        status = "已找回" if hits else ("已检验但未达标" if (s["exposure"], s["outcome"]) in tested else "未检验")
        rows.append({**s, "status": status, "hypothesis_ids": [c["hypothesis"]["id"] for c in hits]})
    false = [c for c in meaningful if c["hypothesis"]["exposure"] in nulls]
    planted_pairs = {(s["exposure"], s["outcome"]) for s in planted}
    other = [c for c in meaningful if c["hypothesis"]["exposure"] not in nulls
             and (c["hypothesis"]["exposure"], c["hypothesis"]["outcome"]) not in planted_pairs]
    found = sum(r["status"] == "已找回" for r in rows)
    return {
        "n_planted": len(planted), "n_found": found, "recall": found / len(planted) if planted else None,
        "rows": rows,
        "false_signals": [{"hypothesis_id": c["hypothesis"]["id"], "exposure": c["hypothesis"]["exposure"],
                           "outcome": c["hypothesis"]["outcome"]} for c in false],
        "other_meaningful": [{"hypothesis_id": c["hypothesis"]["id"], "exposure": c["hypothesis"]["exposure"],
                              "outcome": c["hypothesis"]["outcome"]} for c in other],
        "note_zh": "「其他结论」指未植入但被判为有意义的结论，常见原因是它与某个植入信号高度相关"
                   "（例如 2 型糖尿病、HbA1c 之于糖尿病），不计为假信号；假信号只统计明确无关的字段。",
    }
