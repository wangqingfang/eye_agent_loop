"""离线规则引擎：不调用任何大模型，用确定性规则完成各阶段的判断。

用途：自动化测试，以及没有 API Key 时由技术同事调试整条流程。它的判断远不如真实大模型，
报告中会注明「离线规则引擎」，其结论不应用于研究。
"""

from __future__ import annotations

import json

from .llm import LLMResponse
from .prompts import read_context


def _tool_results(messages):
    """返回 {tool_call_id: 结果}。"""
    return {m["tool_call_id"]: json.loads(m["content"]) for m in messages if m.get("role") == "tool"}


def _resp(payload=None, calls=None, ctx_size=0):
    content = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    return LLMResponse(content=content, tool_calls=calls or [], tokens=200 + (ctx_size + len(content)) // 3)


class OfflineRuleLLM:
    name = "离线规则引擎"

    def chat(self, stage, messages, tools=None, json_mode=False) -> LLMResponse:
        ctx = read_context(messages)
        size = len(json.dumps(messages, ensure_ascii=False, default=str))
        results = _tool_results(messages)
        handler = getattr(self, f"_{stage}")
        payload, calls = handler(ctx, results, tools)
        return _resp(payload, calls, size)

    # ---- 数据发现 ----
    def _discovery(self, ctx, results, tools):
        if not results and tools:
            calls = [{"id": f"screen_{i}", "name": "screen_associations",
                      "arguments": {"outcome": o["outcome"], "population": o["population"]}}
                     for i, o in enumerate(ctx["outcomes"])]
            return None, calls
        tested = set(ctx.get("previous", {}).get("tested", []))
        rows = []
        for res in results.values():
            for r in res.get("top", []):
                key = f"{r['exposure']}|{res['outcome']}"
                if r["p"] < 1e-3 and key not in tested:
                    rows.append((r["p"], r["exposure"], res["outcome"], res["population"], r["estimate"]))
        rows.sort()
        findings = [{"exposure": e, "outcome": o, "population": pop,
                     "summary_zh": f"探索集中{'较高' if est > 1 else '较低'}的关联（OR={est:.2f}，p={p:.1e}）"}
                    for p, e, o, pop, est in rows[: ctx.get("max_findings", 4)]]
        return {"findings": findings}, []

    # ---- 文献检索 ----
    def _literature(self, ctx, results, tools):
        findings = ctx.get("findings", [])
        if not results and tools:
            calls = []
            for f in findings:
                q = f"{f['exposure_term']} {f['outcome_term']}"
                calls.append({"id": f"lit_{f['id']}", "name": "search_literature", "arguments": {"query": q, "finding_id": f["id"]}})
                calls.append({"id": f"ot_{f['id']}", "name": "opentargets_disease_targets",
                              "arguments": {"disease": f["exposure_term"], "finding_id": f["id"]}})
            if findings:
                f = findings[0]
                calls.append({"id": f"trial_{f['id']}", "name": "search_trials",
                              "arguments": {"query": f"{f['exposure_term']} dry eye", "finding_id": f["id"]}})
            return None, calls
        if tools and not any(k.startswith("full_") for k in results):
            for k, res in results.items():
                if k.startswith("lit_"):
                    oa = [r for r in res if r.get("open_access")]
                    if oa:
                        return None, [{"id": f"full_{oa[0]['pmid']}", "name": "fetch_fulltext", "arguments": {"pmid": oa[0]["pmid"]}}]
        notes = []
        for f in findings:
            n = len(results.get(f"lit_{f['id']}", []))
            notes.append({"finding_id": f["id"], "summary_zh": f"检索到 {n} 篇相关文献。"})
        return {"notes": notes}, []

    # ---- 假设生成 ----
    def _hypothesis(self, ctx, results, tools):
        lit, ot = ctx.get("literature", []), ctx.get("opentargets", [])
        out = []
        for f in ctx.get("findings", [])[: ctx.get("max_hypotheses", 4)]:
            cites = [r["pmid"] for r in lit if f["id"] in r.get("finding_ids", [])][:2]
            targets = [r for r in ot if f["id"] in r.get("finding_ids", []) and r.get("symbol")][:2]
            method = "propensity_matching" if f["exposure"].endswith("_exposure") and f.get("binary") else "logistic_regression"
            up = f["estimate"] > 1
            out.append({
                "finding_id": f["id"], "exposure": f["exposure"], "outcome": f["outcome"], "population": f["population"],
                "method": method, "expected_direction": "增加" if up else "降低",
                "statement_zh": f"{f['exposure_zh']}{'增加' if up else '降低'}{f['outcome_zh']}的风险",
                "target_zh": "、".join(t["symbol"] for t in targets) or "暂无",
                "rationale_zh": f"探索集 OR={f['estimate']:.2f}；检索到 {len(cites)} 篇相关文献。",
                "citations": cites, "ot_evidence": [t["id"] for t in targets],
                "novelty": "文献支持" if cites else "文献未见"})
        return {"hypotheses": out}, []

    # ---- 审稿 ----
    def _review(self, ctx, results, tools):
        reviews = []
        for h in ctx.get("hypotheses", []):
            f = h.get("finding", {})
            ok = f.get("p") is not None and f["p"] < 1e-4 and not (f["ci_low"] <= 1 <= f["ci_high"])
            reviews.append({"hypothesis_id": h["id"], "decision": "通过" if ok else "剔除",
                            "reason_zh": "探索集证据充分" if ok else "探索集证据不足（p≥1e-4 或置信区间跨过 1）"})
        return {"reviews": reviews}, []
