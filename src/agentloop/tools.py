"""把统计工具和外部来源包装成 LLM 可调用的工具（tool calling schema + 执行器）。"""

from __future__ import annotations

from . import stats_tools as st
from .dictionary import OUTCOMES


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_POP = {"type": "string", "enum": list(st.POPULATIONS), "description": "分析人群；干眼分型结局只能用「干眼患者」"}
_OUT = {"type": "string", "enum": list(OUTCOMES), "description": "结局字段"}


class DataToolbox:
    """数据发现阶段的统计工具，只绑定探索集。"""

    def __init__(self, df, dictionary):
        self.df = df
        self.dictionary = dictionary
        self.exposures = dictionary.exposures_in(df.columns)
        self.log: list[dict] = []

    def schemas(self):
        exp = {"type": "string", "description": "暴露字段（英文变量名，见 exposure_catalog）"}
        return [
            _fn("screen_associations", "对所有暴露字段逐个做调整混杂的 logistic 回归，返回按 p 值排序的前若干名",
                {"outcome": _OUT, "population": _POP}, ["outcome"]),
            _fn("logistic_regression", "调整年龄、性别、眼科就诊次数后的 logistic 回归，返回 OR、95%CI、p",
                {"exposure": exp, "outcome": _OUT, "population": _POP}, ["exposure", "outcome"]),
            _fn("cox_regression", "以首次眼科就诊为起点、干眼诊断为事件的 Cox 回归，返回 HR",
                {"exposure": exp, "population": _POP}, ["exposure"]),
            _fn("propensity_matching", "倾向评分 1:1 匹配后比较结局（仅适用于有/无暴露）",
                {"exposure": exp, "outcome": _OUT, "population": _POP}, ["exposure", "outcome"]),
            _fn("compare_groups", "暴露组与非暴露组结局率的粗比较（不调整混杂）",
                {"exposure": exp, "outcome": _OUT, "population": _POP}, ["exposure", "outcome"]),
            _fn("describe", "字段的描述统计（记录数、缺失数、比例或均值）",
                {"fields": {"type": "array", "items": {"type": "string"}}, "population": _POP}, ["fields"]),
        ]

    def call(self, name, args):
        args = dict(args or {})
        pop = args.get("population", "全体")
        try:
            if name == "describe":
                res = st.describe(self.df, list(args.get("fields", []))[:20], pop)
            elif name == "screen_associations":
                res = st.screen_associations(self.df, self.exposures, self._outcome(args), pop)
            else:
                exposure = args.get("exposure", "")
                if exposure not in self.exposures:
                    res = {"error": f"「{exposure}」不是可用的暴露字段，请从 exposure_catalog 中选择"}
                elif name == "logistic_regression":
                    res = st.logistic_regression(self.df, exposure, self._outcome(args), pop)
                elif name == "cox_regression":
                    res = st.cox_regression(self.df, exposure, pop)
                elif name == "propensity_matching":
                    res = st.propensity_matching(self.df, exposure, self._outcome(args), pop)
                elif name == "compare_groups":
                    res = st.compare_groups(self.df, exposure, self._outcome(args), pop)
                else:
                    res = {"error": f"没有名为 {name} 的工具"}
        except ValueError as exc:
            res = {"error": str(exc)}
        self.log.append({"tool": name, "arguments": args})
        return res

    @staticmethod
    def _outcome(args):
        outcome = args.get("outcome", "dry_eye_confirmed")
        if outcome not in OUTCOMES:
            raise ValueError(f"「{outcome}」不是可用的结局字段")
        return outcome


class LiteratureToolbox:
    """文献检索阶段的工具。所有检索到的条目都记下来，作为本轮引用校验的白名单。"""

    def __init__(self, sources, max_fulltext=3):
        self.sources = sources
        self.max_fulltext = max_fulltext
        self.literature: dict[str, dict] = {}
        self.trials: dict[str, dict] = {}
        self.opentargets: dict[str, dict] = {}
        self.fulltexts = 0
        self.log: list[dict] = []

    def schemas(self):
        fid = {"type": "string", "description": "对应的表型发现 id"}
        q = {"type": "string", "description": "英文检索词"}
        return [
            _fn("search_literature", "检索 Europe PMC 与 PubMed 的近 10 年文献", {"query": q, "finding_id": fid}, ["query"]),
            _fn("search_trials", "检索 ClinicalTrials.gov 临床试验", {"query": q, "finding_id": fid}, ["query"]),
            _fn("opentargets_disease_targets", "Open Targets：与某疾病相关的靶点",
                {"disease": {"type": "string", "description": "英文疾病名"}, "finding_id": fid}, ["disease"]),
            _fn("opentargets_target_drugs", "Open Targets：作用于某靶点的药物",
                {"symbol": {"type": "string", "description": "基因符号，如 IL6"}, "finding_id": fid}, ["symbol"]),
            _fn("fetch_fulltext", "读取开放获取文献的全文片段", {"pmid": {"type": "string"}}, ["pmid"]),
        ]

    def _keep(self, store, records, finding_id):
        for r in records:
            item = store.setdefault(r["id"], {**r, "finding_ids": []})
            if finding_id and finding_id not in item["finding_ids"]:
                item["finding_ids"].append(finding_id)
        return records

    def call(self, name, args):
        args = dict(args or {})
        fid = args.get("finding_id", "")
        if name == "search_literature":
            q = args.get("query", "")
            merged = {r["pmid"]: r for r in self.sources.pubmed(q) + self.sources.europe_pmc(q)}
            recs = self._keep(self.literature, list(merged.values()), fid)
            res = [{k: r[k] for k in ("pmid", "title", "year", "journal", "open_access")} | {"abstract": r["abstract"][:500]}
                   for r in recs]
        elif name == "search_trials":
            res = self._keep(self.trials, self.sources.trials(args.get("query", "")), fid)
        elif name == "opentargets_disease_targets":
            res = self._keep(self.opentargets, self.sources.disease_targets(args.get("disease", "")), fid)
        elif name == "opentargets_target_drugs":
            res = self._keep(self.opentargets, self.sources.target_drugs(args.get("symbol", "")), fid)
        elif name == "fetch_fulltext":
            rec = self.literature.get(str(args.get("pmid", "")))
            if not rec or not rec.get("pmcid") or not rec.get("open_access"):
                res = {"error": "该文献不在本轮检索结果中，或不是开放获取"}
            elif self.fulltexts >= self.max_fulltext:
                res = {"error": f"本轮全文读取已达上限 {self.max_fulltext} 篇"}
            else:
                self.fulltexts += 1
                rec["fulltext_excerpt"] = self.sources.fulltext(rec["pmcid"])[:2000]
                res = {"pmid": rec["pmid"], "excerpt": rec["fulltext_excerpt"]}
        else:
            res = {"error": f"没有名为 {name} 的工具"}
        self.log.append({"tool": name, "arguments": args})
        return res
