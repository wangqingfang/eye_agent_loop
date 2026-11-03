"""把运行目录的内容整理成与格式无关的「报告块」，HTML 与 Word 共用同一份内容。

块的类型：("h1"|"h2"|"h3", 文本)、("p", 文本)、("warn", 文本)、("table", 表头, 行)、("img", png, 说明)。
表格单元格可以是字符串，或 {"text": 文本, "href": 链接}。
"""

from __future__ import annotations

from . import charts
from .stages import STAGE_ZH


def fmt_eff(r):
    if not r or r.get("estimate") is None:
        return "已抑制" if r and r.get("suppressed") else "—"
    return f"{r['estimate']:.2f}（{r['ci_low']:.2f}–{r['ci_high']:.2f}）"


def fmt_p(p):
    if p is None:
        return "—"
    return f"{p:.2e}" if p < 0.001 else f"{p:.3f}"


def _pmid_cell(pmid, source=""):
    if "离线" in (source or ""):
        return f"PMID {pmid}（离线模拟）"
    return {"text": f"PMID {pmid}", "href": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}


def _label(h):
    return f"{h['id']} {h['exposure_zh']}→{h['outcome_zh']}"


def header_blocks(state, n_tests):
    b = [("h1", "干眼共病研究循环 · 研究报告")]
    data = "合成数据（虚拟患者，结论无医学意义，仅用于检验程序）" if state["synthetic"] else f"真实数据：{state['data_dir']}"
    status = {"completed": "已完成", "paused": "已暂停（可继续）", "running": "进行中"}[state["status"]]
    b.append(("table", ["项目", "内容"], [
        ["运行编号", state["run_id"]], ["开始时间", state["created"]], ["数据", data],
        ["探索集 / 验证集人数", f"{state.get('split', {}).get('探索集', '—')} / {state.get('split', {}).get('验证集', '—')}"],
        ["大模型", f"{state['config']['model']}（{state['config']['base_url']}）" if state["llm_mode"] == "online" else "离线规则引擎（未调用大模型）"],
        ["外部来源", "Europe PMC、PubMed、ClinicalTrials.gov、Open Targets（在线）" if state["sources_mode"] == "online" else "离线模拟来源（未联网）"],
        ["状态", status + (f"：{state['stop_reason']}" if state["stop_reason"] else "")],
        ["已完成轮次", str(len(state["rounds"]))], ["累计验证检验数（FDR 校正范围）", str(n_tests)],
        ["累计 token 用量", f"{state['tokens_total']:,}"],
        ["组学模块", ("已启用：" if state.get("omics", {}).get("enabled") else "未启用：") + state.get("omics", {}).get("reason_zh", "")]]))
    if state["llm_mode"] != "online":
        b.append(("warn", "本次运行使用「离线规则引擎」代替大模型，只用于调试流程，结论不应用于研究。"))
    if state["sources_mode"] != "online":
        b.append(("warn", "本次运行使用离线模拟文献与靶点，文献条目是虚构的，只用于调试流程。"))
    if state["synthetic"]:
        b.append(("warn", "本次运行使用合成数据。合成数据中的结论没有任何医学意义，只用来评估研究循环本身（见文末评测章节）。"))
    b.append(("warn", "所有结论都是基于回顾性数据的统计关联与文献推理，属于值得进一步研究的线索，不等于因果关系，"
                      "也不是诊疗建议。用于申报、论文或临床前，必须由临床专家和统计人员复核。"))
    return b


def progress_blocks(state, concl):
    b = [("h2", "一、进展总览")]
    png = charts.progress_chart(state["rounds"])
    if png:
        b.append(("img", png, "图 1  各轮提出的假设数、通过审稿数与有意义结论数"))
    validated = [c for c in concl if c["result"].get("estimate")]
    png = charts.effects_chart([{"label": _label(c["hypothesis"]), "highlight": c["meaningful"], **c["result"]}
                                for c in validated], "验证集上的效应量与 95% 置信区间（红色为有意义结论）")
    if png:
        b.append(("img", png, "图 2  所有已验证假设在验证集上的效应量（按轮次先后排列）"))
    rows = [[f"第{r['round']}轮", r["n_findings"], r["n_hypotheses"], r["n_passed_review"], r["n_validated"],
             len(r["new_meaningful"]), r["cumulative_meaningful"], f"{r['tokens_total']:,}"] for r in state["rounds"]]
    if rows:
        b.append(("table", ["轮次", "表型发现", "提出假设", "通过审稿", "完成验证", "新增有意义结论", "累计有意义结论", "累计 token"],
                  [[str(x) for x in row] for row in rows]))
    return b


def conclusion_blocks(concl):
    b = [("h2", "二、有意义结论清单"),
         ("p", "判定标准（由程序判定，不由大模型宣布）：在验证集上经全部轮次累计的 FDR 校正后 q < 0.05，"
               "且效应方向与登记时的预期一致；并标明有文献支持，或明确标为文献未见的新发现。")]
    rows = [[c["hypothesis"]["id"], c["hypothesis"]["statement_zh"], c["hypothesis"]["population"],
             c["result"]["method"], fmt_eff(c["result"]), fmt_p(c["result"]["p"]), fmt_p(c["q"]),
             c["hypothesis"]["novelty"], c["hypothesis"].get("target_zh") or "—"] for c in concl if c["meaningful"]]
    if rows:
        b.append(("table", ["编号", "结论", "人群", "方法", "效应量（95%CI）", "p", "校正后 q", "文献", "涉及靶点/通路"], rows))
    else:
        b.append(("p", "目前还没有有意义结论。"))
    return b


def round_blocks(r, outs, concl_by_id):
    b = [("h2", f"第 {r} 轮")]
    if not outs:
        return []
    d = outs.get("discovery")
    if d:
        b.append(("h3", "1. 数据发现（探索集）"))
        rows = [[f["id"], f["exposure_zh"], f["outcome_zh"], f["population"], f.get("evidence_level") or "—",
                 f"{fmt_eff(f)} {f.get('unit', '')}", fmt_p(f["p"]), str(f["n"]), f.get("source", "")] for f in d["findings"]]
        b.append(("table", ["编号", "暴露", "结局", "人群", "数据字典证据等级", "OR（95%CI）", "p", "样本量", "来源"], rows)
                 if rows else ("p", "本轮没有新的表型发现。"))
        if d.get("dropped"):
            b.append(("p", "未采纳的候选：" + "；".join(f"{x.get('exposure', '')}→{x.get('outcome', '')}（{x['reason_zh']}）" for x in d["dropped"])))
    lit = outs.get("literature")
    if lit and (lit["literature"] or lit["trials"] or lit["opentargets"]):
        b.append(("h3", "2. 文献检索"))
        for n in lit.get("notes", []):
            b.append(("p", f"{n.get('finding_id', '')}：{n.get('summary_zh', '')}"))
        rows = [[_pmid_cell(x["pmid"], x.get("source")), x["title"], str(x.get("year") or ""), x.get("journal") or "",
                 "、".join(x.get("finding_ids", [])), "是" if x.get("fulltext_excerpt") else ""] for x in lit["literature"]]
        if rows:
            b.append(("table", ["文献", "标题（英文原题）", "年份", "期刊", "对应发现", "已读全文"], rows))
        rows = [[{"text": t["id"], "href": f"https://clinicaltrials.gov/study/{t['id']}"} if "离线" not in t.get("source", "") else t["id"],
                 t.get("title") or "", t.get("phase") or "", t.get("status") or ""] for t in lit["trials"]]
        if rows:
            b.append(("table", ["临床试验", "标题", "分期", "状态"], rows))
        rows = [[o.get("symbol") or "", o.get("target_name") or o.get("drug") or "", o.get("disease") or o.get("stage") or "",
                 str(o.get("score", "")), "、".join(o.get("finding_ids", []))] for o in lit["opentargets"]]
        if rows:
            b.append(("table", ["靶点", "靶点名 / 药物", "疾病 / 临床阶段", "关联得分", "对应发现"], rows))
        if lit.get("failures"):
            b.append(("p", "以下来源本轮请求失败，已跳过：" + "；".join(f"{f['source']}（{f['error'][:60]}）" for f in lit["failures"])))
    h = outs.get("hypothesis")
    if h and (h["hypotheses"] or h["invalid"]):
        b.append(("h3", "3. 假设生成"))
        rows = [[x["id"], x["statement_zh"], x.get("target_zh") or "—", x["method"], x["expected_direction"],
                 "、".join(x["citations"]) or "—", x["novelty"], x.get("rationale_zh", "")] for x in h["hypotheses"]]
        if rows:
            b.append(("table", ["编号", "靶点假设", "涉及靶点/通路", "检验方法", "预期方向", "引用 PMID", "文献", "推理依据"], rows))
        if h["removed_citations"]:
            b.append(("table", ["假设", "被删除的引用", "原因"],
                      [[x["hypothesis_id"], x["citation"], x["reason_zh"]] for x in h["removed_citations"]]))
        if h["invalid"]:
            b.append(("p", "被拒收的假设：" + "；".join(f"{x.get('statement_zh', '')}（{x['reason_zh']}）" for x in h["invalid"])))
    rv = outs.get("review")
    if rv and rv["reviews"]:
        b.append(("h3", "4. 审稿"))
        b.append(("table", ["假设", "审稿结论", "理由"], [[x["hypothesis_id"], x["decision"], x["reason_zh"]] for x in rv["reviews"]]))
    v = outs.get("validate")
    if v and v["results"]:
        b.append(("h3", "5. 登记与验证（验证集）"))
        rows = []
        for res in v["results"]:
            c = concl_by_id.get(res["hypothesis_id"], {})
            rows.append([res["hypothesis_id"], res["method"], fmt_eff(res), fmt_p(res["p"]), fmt_p(c.get("q")),
                         {True: "一致", False: "相反", None: "—"}[res["direction_ok"]], "是" if c.get("meaningful") else "否"])
        b.append(("table", ["假设", "方法", "效应量（95%CI）", "p", "当前 q", "方向", "有意义结论"], rows))
        png = charts.effects_chart([{"label": _label(concl_by_id[x["hypothesis_id"]]["hypothesis"]),
                                     "highlight": concl_by_id[x["hypothesis_id"]]["meaningful"], **x}
                                    for x in v["results"] if x["hypothesis_id"] in concl_by_id], f"第 {r} 轮验证结果")
        if png:
            b.append(("img", png, f"第 {r} 轮验证集效应量"))
    pending = [STAGE_ZH[s] for s in STAGE_ZH if s not in outs]
    if pending:
        b.append(("p", "本轮尚未完成的阶段：" + "、".join(pending)))
    return b


def evaluation_blocks(ev):
    if not ev:
        return []
    b = [("h2", "评测：植入信号找回情况（仅合成数据）"),
         ("p", f"合成数据中共植入 {ev['n_planted']} 个信号，找回 {ev['n_found']} 个"
               f"（找回率 {ev['recall'] * 100:.0f}%）；明确无关字段被误判为有意义结论 {len(ev['false_signals'])} 个。")]
    b.append(("table", ["暴露", "结局", "植入强度（对数 OR）", "类别", "找回情况", "对应假设"],
              [[x["exposure"], x["outcome"], f"{x['log_or']:.2f}", x["kind"], x["status"], "、".join(x["hypothesis_ids"]) or "—"]
               for x in ev["rows"]]))
    if ev["false_signals"]:
        b.append(("table", ["假信号", "暴露", "结局"], [[x["hypothesis_id"], x["exposure"], x["outcome"]] for x in ev["false_signals"]]))
    if ev["other_meaningful"]:
        b.append(("p", "其他有意义结论（未植入）：" + "；".join(f"{x['hypothesis_id']} {x['exposure']}→{x['outcome']}" for x in ev["other_meaningful"])))
        b.append(("p", ev["note_zh"]))
    return b


METHOD_NOTE = [
    ("h2", "方法说明"),
    ("p", "探索集与验证集在研究开始时按患者一次性随机划分并保存，之后任何轮次都不重新划分。表型发现只在探索集上产生；"
          "靶点假设通过审稿后先登记（登记后不可修改），再在验证集上检验。"),
    ("p", "关联分析默认调整年龄、性别和索引日期前 365 天眼科就诊次数（就诊越多越容易被诊断，属于检测偏倚）。"
          "缺失值按数据字典规则处理：0=明确否认，1=明确存在，NA=未记录；NA 不当作 0，分析时按完整病例排除。"
          "连续变量的效应量为每增加 1 个标准差。"),
    ("p", "多重检验：所有轮次的验证检验累计做 Benjamini-Hochberg FDR 校正，新检验加入后历史结论的 q 值会随之更新。"),
    ("p", "隐私：大模型只看到数据字典和汇总统计；人数少于 10 的分组结果在送给大模型和写入报告前一律抑制。"),
]


def build(state, rounds, concl, ev, n_tests):
    by_id = {c["hypothesis"]["id"]: c for c in concl}
    blocks = header_blocks(state, n_tests) + progress_blocks(state, concl) + conclusion_blocks(concl)
    blocks.append(("h2", "三、各轮详情"))
    for r in sorted(rounds):
        blocks += round_blocks(r, rounds[r], by_id)
    return blocks + evaluation_blocks(ev) + METHOD_NOTE
