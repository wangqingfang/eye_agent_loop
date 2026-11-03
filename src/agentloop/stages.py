"""研究轮次的五个阶段（ADR 0004）：数据发现 → 文献检索 → 假设生成 → 审稿 → 登记与验证。

每个阶段只开放本阶段的工具；LLM 只在阶段内做判断，阶段顺序由代码保证。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import omics, prompts
from . import stats_tools as st
from .dictionary import CASE_ONLY_OUTCOMES, OUTCOMES, DataDictionary
from .llm import assistant_message, parse_json, tool_message
from .tools import DataToolbox, LiteratureToolbox

STAGES = ["discovery", "literature", "hypothesis", "review", "validate"]
STAGE_ZH = {"discovery": "数据发现", "literature": "文献检索", "hypothesis": "假设生成",
            "review": "审稿", "validate": "登记与验证"}
MAX_FINDINGS = 4
MAX_HYPOTHESES = 4


@dataclass
class Env:
    dictionary: DataDictionary
    data: object  # DataAccess
    registry: object
    ledger: object
    llm: object  # GuardedLLM
    sources: object
    max_fulltext: int = 3
    omics_fields: list = field(default_factory=list)


def run_tool_loop(llm, stage, system, context, toolbox=None, max_steps=10):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompts.user_message(context)}]
    tools = toolbox.schemas() if toolbox else None
    for _ in range(max_steps):
        resp = llm.chat(stage, messages, tools=tools, json_mode=tools is None)
        if resp.tool_calls and toolbox:
            messages.append(assistant_message(resp))
            for call in resp.tool_calls:
                messages.append(tool_message(call["id"], toolbox.call(call["name"], call["arguments"])))
            continue
        parsed = parse_json(resp.content)
        if parsed is not None:
            return parsed
        messages.append(assistant_message(resp))
        messages.append({"role": "user", "content": "请只输出符合要求的 JSON 对象。"})
    resp = llm.chat(stage, messages + [{"role": "user", "content": "工具调用次数已用完，请直接输出最终 JSON。"}],
                    tools=None, json_mode=True)
    return parse_json(resp.content) or {}


def _norm_population(outcome, population):
    return "干眼患者" if outcome in CASE_ONLY_OUTCOMES or population == "干眼患者" else "全体"


def _stat_view(r):
    return {k: r.get(k) for k in ["estimate", "ci_low", "ci_high", "p", "n", "unit", "effect_measure"]}


# ---------------- 1. 数据发现 ----------------
def discovery(env: Env, round_no: int, previous: dict) -> dict:
    df = env.data.exploration()
    toolbox = DataToolbox(df, env.dictionary)
    outcomes = [{"outcome": o, "zh": zh, "population": _norm_population(o, "全体")}
                for o, zh in OUTCOMES.items() if o in df.columns]
    context = {"stage": "discovery", "round": round_no, "outcomes": outcomes,
               "exposure_catalog": env.dictionary.catalog(df.columns), "previous": previous,
               "max_findings": MAX_FINDINGS}
    raw = run_tool_loop(env.llm, "discovery", prompts.DISCOVERY, context, toolbox)
    tested = set(previous.get("tested", []))
    findings, dropped = [], []
    candidates = list(raw.get("findings", []))
    if env.omics_fields:  # 组学模块的发现排在前面，重复时以组学模块为来源
        candidates = omics.findings(df, env.omics_fields, tested) + candidates
    for item in candidates:
        e, o = item.get("exposure", ""), item.get("outcome", "")
        key = f"{e}|{o}"
        if e not in toolbox.exposures or o not in OUTCOMES:
            dropped.append({**item, "reason_zh": "字段不存在或不可用"})
            continue
        if key in tested or any(f"{f['exposure']}|{f['outcome']}" == key for f in findings):
            dropped.append({**item, "reason_zh": "与此前的发现重复"})
            continue
        pop = _norm_population(o, item.get("population", "全体"))
        stat = st.logistic_regression(df, e, o, pop)  # 用代码复算，不采信 LLM 转述的数字
        if stat["suppressed"]:
            dropped.append({**item, "reason_zh": stat["note"]})
            continue
        findings.append({"id": f"F{round_no}-{len(findings) + 1}", "exposure": e, "outcome": o, "population": pop,
                         "exposure_zh": env.dictionary.zh(e), "outcome_zh": env.dictionary.zh(o),
                         "evidence_level": env.dictionary.evidence(e), "binary": st.is_binary(df[e]),
                         "source": item.get("source", "数据发现"), "summary_zh": item.get("summary_zh", ""),
                         **_stat_view(stat)})
    return {"findings": findings, "dropped": dropped, "tool_log": toolbox.log, "n_exploration": len(df)}


# ---------------- 2. 文献检索 ----------------
def literature(env: Env, round_no: int, outputs: dict) -> dict:
    findings = outputs["discovery"]["findings"]
    if not findings:
        return {"notes": [], "literature": [], "trials": [], "opentargets": [], "failures": [], "tool_log": []}
    before = len(env.sources.failures)
    toolbox = LiteratureToolbox(env.sources, env.max_fulltext)
    ctx_findings = [{"id": f["id"], "exposure": f["exposure"], "exposure_zh": f["exposure_zh"],
                     "outcome": f["outcome"], "outcome_zh": f["outcome_zh"],
                     "exposure_term": env.dictionary.search_term(f["exposure"]),
                     "outcome_term": env.dictionary.search_term(f["outcome"]),
                     "estimate": f["estimate"], "p": f["p"]} for f in findings]
    context = {"stage": "literature", "round": round_no, "findings": ctx_findings, "max_fulltext": env.max_fulltext}
    raw = run_tool_loop(env.llm, "literature", prompts.LITERATURE, context, toolbox, max_steps=12)
    return {"notes": raw.get("notes", []), "literature": list(toolbox.literature.values()),
            "trials": list(toolbox.trials.values()), "opentargets": list(toolbox.opentargets.values()),
            "failures": env.sources.failures[before:], "tool_log": toolbox.log}


# ---------------- 3. 假设生成（含引用校验） ----------------
def _method_ok(method, outcome, binary):
    if method not in st.METHODS:
        return False
    if method == "cox_regression" and outcome != "dry_eye_confirmed":
        return False
    return not (method == "propensity_matching" and not binary)


def hypothesis(env: Env, round_no: int, outputs: dict) -> dict:
    findings = {f["id"]: f for f in outputs["discovery"]["findings"]}
    lit = outputs["literature"]
    if not findings:
        return {"hypotheses": [], "invalid": [], "removed_citations": []}
    context = {
        "stage": "hypothesis", "round": round_no, "findings": list(findings.values()),
        "literature": [{"pmid": r["pmid"], "title": r["title"], "year": r.get("year"), "journal": r.get("journal"),
                        "abstract": (r.get("abstract") or "")[:400], "fulltext_excerpt": (r.get("fulltext_excerpt") or "")[:600],
                        "finding_ids": r.get("finding_ids", [])} for r in lit["literature"]],
        "trials": [{k: r.get(k) for k in ("id", "title", "phase", "status", "finding_ids")} for r in lit["trials"]],
        "opentargets": [{k: r.get(k) for k in ("id", "symbol", "target_name", "drug", "stage", "disease", "finding_ids")}
                        for r in lit["opentargets"]],
        "notes": lit["notes"], "allowed_methods": st.METHODS, "max_hypotheses": MAX_HYPOTHESES}
    raw = run_tool_loop(env.llm, "hypothesis", prompts.HYPOTHESIS, context)
    pmids = {r["pmid"] for r in lit["literature"]}
    ot_ids = {r["id"] for r in lit["opentargets"]}
    registered = {(h["exposure"], h["outcome"], h["population"], h["method"]) for h in env.registry.all()}
    hyps, invalid, removed = [], [], []
    for item in raw.get("hypotheses", [])[: MAX_HYPOTHESES * 2]:
        f = findings.get(item.get("finding_id"))
        e = item.get("exposure") or (f or {}).get("exposure")
        o = item.get("outcome") or (f or {}).get("outcome")
        if not f or e != f["exposure"] or o != f["outcome"]:
            invalid.append({**item, "reason_zh": "假设必须对应本轮的某个表型发现（暴露与结局一致）"})
            continue
        pop = _norm_population(o, item.get("population", f["population"]))
        method = item.get("method", "logistic_regression")
        note = ""
        if not _method_ok(method, o, f["binary"]):
            note = f"方法「{method}」不适用，已改为 logistic 回归"
            method = "logistic_regression"
        if (e, o, pop, method) in registered or any((h["exposure"], h["outcome"], h["population"], h["method"]) == (e, o, pop, method) for h in hyps):
            invalid.append({**item, "reason_zh": "与已登记的假设重复"})
            continue
        hid = f"H{round_no}-{len(hyps) + 1}"
        cites, bad = [], []
        for c in item.get("citations", []) or []:
            (cites if str(c) in pmids else bad).append(str(c))
        for c in bad:
            removed.append({"hypothesis_id": hid, "citation": c, "reason_zh": "不在本轮实际检索到的文献中，已删除"})
        ots = [str(x) for x in item.get("ot_evidence", []) or [] if str(x) in ot_ids]
        for x in item.get("ot_evidence", []) or []:
            if str(x) not in ot_ids:
                removed.append({"hypothesis_id": hid, "citation": str(x), "reason_zh": "不在本轮实际查询到的 Open Targets 条目中，已删除"})
        direction = item.get("expected_direction")
        if direction not in ("增加", "降低"):
            direction = "增加" if f["estimate"] > 1 else "降低"
        novelty = "文献支持" if cites else "文献未见"
        hyps.append({"id": hid, "round": round_no, "finding_id": f["id"], "exposure": e, "outcome": o,
                     "population": pop, "method": method, "expected_direction": direction,
                     "exposure_zh": f["exposure_zh"], "outcome_zh": f["outcome_zh"],
                     "statement_zh": item.get("statement_zh") or f"{f['exposure_zh']}与{f['outcome_zh']}相关",
                     "target_zh": item.get("target_zh", ""), "rationale_zh": item.get("rationale_zh", ""),
                     "citations": cites, "ot_evidence": ots, "novelty": novelty, "note_zh": note})
    return {"hypotheses": hyps, "invalid": invalid, "removed_citations": removed}


# ---------------- 4. 审稿 ----------------
def review(env: Env, round_no: int, outputs: dict) -> dict:
    hyps = outputs["hypothesis"]["hypotheses"]
    if not hyps:
        return {"reviews": [], "passed": []}
    findings = {f["id"]: f for f in outputs["discovery"]["findings"]}
    titles = {r["pmid"]: r["title"] for r in outputs["literature"]["literature"]}
    context = {"stage": "review", "round": round_no, "hypotheses": [
        {"id": h["id"], "statement_zh": h["statement_zh"], "exposure_zh": h["exposure_zh"], "outcome_zh": h["outcome_zh"],
         "population": h["population"], "method": h["method"], "expected_direction": h["expected_direction"],
         "rationale_zh": h["rationale_zh"], "novelty": h["novelty"],
         "finding": _stat_view(findings[h["finding_id"]]),
         "cited_titles": [titles[c] for c in h["citations"] if c in titles]} for h in hyps]}
    raw = run_tool_loop(env.llm, "review", prompts.REVIEW, context)
    by_id = {r.get("hypothesis_id"): r for r in raw.get("reviews", [])}
    reviews = []
    for h in hyps:
        r = by_id.get(h["id"], {})
        decision = r.get("decision") if r.get("decision") in ("通过", "剔除") else "剔除"
        reason = r.get("reason_zh") or ("审稿未给出结论，按剔除处理" if not r else "")
        reviews.append({"hypothesis_id": h["id"], "decision": decision, "reason_zh": reason})
    return {"reviews": reviews, "passed": [r["hypothesis_id"] for r in reviews if r["decision"] == "通过"]}


# ---------------- 5. 登记与验证 ----------------
def validate(env: Env, round_no: int, outputs: dict) -> dict:
    hyps = {h["id"]: h for h in outputs["hypothesis"]["hypotheses"]}
    results = []
    for hid in outputs["review"]["passed"]:
        h = hyps[hid]
        if not env.registry.is_registered(hid):
            env.registry.register(h)  # 先登记，登记后不可修改
        if env.registry.has_result(hid):
            results.append(next(r for r in env.registry.results() if r["hypothesis_id"] == hid))
            continue
        df = env.data.open_validation(hid, env.registry, stage="validate")
        r = st.run_method(df, h["method"], h["exposure"], h["outcome"], h["population"])
        ok = None if r["suppressed"] else ((r["estimate"] > 1) == (h["expected_direction"] == "增加"))
        result = {"hypothesis_id": hid, "round": round_no, **_stat_view(r), "method": h["method"],
                  "suppressed": r["suppressed"], "direction_ok": ok, "note": r.get("note", "")}
        env.registry.append_result(result)
        if not r["suppressed"]:
            env.ledger.add(hid, round_no, r["p"])
        results.append(result)
    return {"results": results, "n_tests_total": env.ledger.n_tests()}


RUNNERS = {"literature": literature, "hypothesis": hypothesis, "review": review, "validate": validate}
