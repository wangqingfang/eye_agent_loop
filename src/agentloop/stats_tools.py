"""预置统计工具（ADR 0002）。

LLM 只能通过这些工具接触数据，每个工具只返回汇总结果，并在返回前抑制样本数小于 10 的分组（ADR 0001）。
默认调整年龄、性别、索引日期前 365 天眼科就诊次数。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as sps

from .dictionary import CASE_ONLY_OUTCOMES, COVARIATES, OUTCOMES

MIN_CELL = 10
POPULATIONS = {"全体": "全部患者", "干眼患者": "仅干眼患者（干眼分型结局必须使用）"}
SUPPRESSED = "<10（已抑制）"


def _numeric(series: pd.Series) -> pd.Series:
    if series.name == "sex":
        return (series.astype(str).str.upper().str.startswith("F")).astype(float).where(series.notna())
    return pd.to_numeric(series, errors="coerce").astype(float)


def _population(df: pd.DataFrame, outcome: str | None, population: str) -> tuple[pd.DataFrame, str]:
    if outcome in CASE_ONLY_OUTCOMES or population == "干眼患者":
        return df[_numeric(df["dry_eye_confirmed"]) == 1], "干眼患者"
    return df, "全体"


def is_binary(series: pd.Series) -> bool:
    values = set(pd.unique(_numeric(series).dropna()))
    return values <= {0.0, 1.0}


def design(df, exposure, outcome, population, extra=()):
    """整理建模数据：完整病例分析（NA=未记录，不当作 0），连续暴露按 1 个标准差缩放。"""
    sub, pop = _population(df, outcome, population)
    covs = [c for c in [*COVARIATES, *extra] if c != exposure and c in sub.columns]
    cols = list(dict.fromkeys([outcome, exposure, *covs]))
    data = pd.DataFrame({c: _numeric(sub[c]) for c in cols}).dropna()
    binary = is_binary(data[exposure])
    if not binary and data[exposure].std() > 0:
        data[exposure] = (data[exposure] - data[exposure].mean()) / data[exposure].std()
    return data, covs, pop, binary


def _base(method, exposure, outcome, pop, covs, binary, measure):
    return {"method": method, "exposure": exposure, "outcome": outcome, "population": pop,
            "covariates": covs, "effect_measure": measure,
            "unit": "有 vs 无" if binary else "每增加 1 个标准差"}


def _suppressed(result, reason):
    result.update({"suppressed": True, "estimate": None, "ci_low": None, "ci_high": None, "p": None,
                   "note": f"{reason}，结果已抑制"})
    return result


def _cells_too_small(data, exposure, outcome, binary):
    if len(data) < MIN_CELL:
        return True
    if not binary:
        return data[outcome].sum() < MIN_CELL or (1 - data[outcome]).sum() < MIN_CELL
    for e in (0, 1):
        grp = data[data[exposure] == e][outcome]
        if len(grp) < MIN_CELL or grp.sum() < MIN_CELL or (1 - grp).sum() < MIN_CELL:
            return True
    return False


def logistic_regression(df, exposure, outcome, population="全体", extra_covariates=()):
    data, covs, pop, binary = design(df, exposure, outcome, population, extra_covariates)
    res = _base("logistic_regression", exposure, outcome, pop, covs, binary, "OR")
    res["n"] = int(len(data))
    if _cells_too_small(data, exposure, outcome, binary):
        return _suppressed(res, "存在样本数小于 10 的分组")
    res["n_exposed"] = int(data[exposure].sum()) if binary else None
    res["events"] = int(data[outcome].sum())
    X = sm.add_constant(data[[exposure, *covs]], has_constant="add")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.Logit(data[outcome], X).fit(disp=0, maxiter=200)
    except Exception as exc:  # 完全分离等
        return _suppressed(res, f"模型无法拟合（{type(exc).__name__}）")
    beta, se = fit.params[exposure], fit.bse[exposure]
    res.update({"suppressed": False, "estimate": float(np.exp(beta)), "ci_low": float(np.exp(beta - 1.96 * se)),
                "ci_high": float(np.exp(beta + 1.96 * se)), "p": float(fit.pvalues[exposure]), "note": ""})
    return res


def _time_to_event(df):
    need = ["first_oph_visit_date", "followup_end_date", "dry_eye_index_date"]
    if any(c not in df.columns for c in need):
        return None
    start = pd.to_datetime(df["first_oph_visit_date"], errors="coerce")
    end = pd.to_datetime(df["dry_eye_index_date"], errors="coerce").fillna(pd.to_datetime(df["followup_end_date"], errors="coerce"))
    return (end - start).dt.days.astype(float)


def cox_regression(df, exposure, population="全体", extra_covariates=()):
    outcome = "dry_eye_confirmed"
    sub, pop = _population(df, outcome, population)
    time = _time_to_event(sub)
    covs = [c for c in [*COVARIATES, *extra_covariates] if c != exposure and c in sub.columns]
    binary = is_binary(sub[exposure])
    res = _base("cox_regression", exposure, outcome, pop, covs, binary, "HR")
    if time is None:
        return _suppressed(res, "数据缺少随访时间字段（first_oph_visit_date / followup_end_date / dry_eye_index_date）")
    data = pd.DataFrame({c: _numeric(sub[c]) for c in dict.fromkeys([outcome, exposure, *covs])})
    data["_time"] = time.to_numpy()
    data = data.dropna()
    data = data[data["_time"] > 0]
    if not binary and data[exposure].std() > 0:
        data[exposure] = (data[exposure] - data[exposure].mean()) / data[exposure].std()
    res["n"] = int(len(data))
    if _cells_too_small(data, exposure, outcome, binary):
        return _suppressed(res, "存在样本数小于 10 的分组")
    res["events"] = int(data[outcome].sum())
    try:
        fit = sm.PHReg(data["_time"], data[[exposure, *covs]], status=data[outcome]).fit(disp=0)
    except Exception as exc:
        return _suppressed(res, f"模型无法拟合（{type(exc).__name__}）")
    beta, se, p = fit.params[0], fit.bse[0], fit.pvalues[0]
    res.update({"suppressed": False, "estimate": float(np.exp(beta)), "ci_low": float(np.exp(beta - 1.96 * se)),
                "ci_high": float(np.exp(beta + 1.96 * se)), "p": float(p), "note": "随访截尾：未发生干眼者截止于随访结束日"})
    return res


def propensity_matching(df, exposure, outcome, population="全体", caliper=0.2):
    data, covs, pop, binary = design(df, exposure, outcome, population)
    res = _base("propensity_matching", exposure, outcome, pop, covs, binary, "OR")
    if not binary:
        return _suppressed(res, "倾向评分匹配只适用于有/无两类的暴露")
    X = sm.add_constant(data[covs], has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logit = sm.Logit(data[exposure], X).fit(disp=0).predict(X)
    score = np.log(logit / (1 - logit))
    width = caliper * score.std()
    treated = data[data[exposure] == 1].assign(_s=score[data[exposure] == 1])
    pool = data[data[exposure] == 0].assign(_s=score[data[exposure] == 0]).sort_values("_s")
    pool_s, used, pairs = pool["_s"].to_numpy(), np.zeros(len(pool), bool), []
    for idx, s in treated["_s"].sort_values().items():
        j = int(np.searchsorted(pool_s, s))
        best = None
        for k in range(max(0, j - 5), min(len(pool_s), j + 5)):
            if not used[k] and abs(pool_s[k] - s) <= width and (best is None or abs(pool_s[k] - s) < abs(pool_s[best] - s)):
                best = k
        if best is not None:
            used[best] = True
            pairs.append((idx, pool.index[best]))
    matched = pd.concat([data.loc[[a for a, _ in pairs]], data.loc[[b for _, b in pairs]]])
    res["n"] = int(len(matched))
    res["n_pairs"] = len(pairs)
    if _cells_too_small(matched, exposure, outcome, True):
        return _suppressed(res, "匹配后存在样本数小于 10 的分组")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = sm.Logit(matched[outcome], sm.add_constant(matched[[exposure]])).fit(disp=0)
    beta, se = fit.params[exposure], fit.bse[exposure]
    rd = matched[matched[exposure] == 1][outcome].mean() - matched[matched[exposure] == 0][outcome].mean()
    res.update({"suppressed": False, "estimate": float(np.exp(beta)), "ci_low": float(np.exp(beta - 1.96 * se)),
                "ci_high": float(np.exp(beta + 1.96 * se)), "p": float(fit.pvalues[exposure]),
                "risk_difference": float(rd), "events": int(matched[outcome].sum()),
                "note": f"1:1 最近邻匹配，卡钳 {caliper} 个标准差"})
    return res


def describe(df, fields, population="全体"):
    sub, pop = _population(df, None, population)
    out = {"population": pop, "n": int(len(sub)), "fields": []}
    for f in fields:
        if f not in sub.columns:
            out["fields"].append({"field": f, "error": "没有这个字段"})
            continue
        s = _numeric(sub[f])
        item = {"field": f, "n_recorded": int(s.notna().sum()), "n_missing": int(s.isna().sum())}
        if is_binary(sub[f]):
            k, m = int(s.sum()), int(s.notna().sum())
            item["n_yes"] = SUPPRESSED if min(k, m - k) < MIN_CELL else k
            item["pct_yes"] = None if min(k, m - k) < MIN_CELL else round(100 * k / max(m, 1), 1)
        elif s.notna().sum() >= MIN_CELL:
            item.update({"mean": round(float(s.mean()), 3), "sd": round(float(s.std()), 3), "median": round(float(s.median()), 3)})
        else:
            item["note"] = SUPPRESSED
        out["fields"].append(item)
    return out


def compare_groups(df, exposure, outcome, population="全体"):
    sub, pop = _population(df, outcome, population)
    data = pd.DataFrame({exposure: _numeric(sub[exposure]), outcome: _numeric(sub[outcome])}).dropna()
    res = {"method": "compare_groups", "exposure": exposure, "outcome": outcome, "population": pop, "n": int(len(data))}
    if not is_binary(data[exposure]):
        return {**res, "error": "分层对比只适用于有/无两类的暴露；连续变量请用 logistic_regression"}
    table = pd.crosstab(data[exposure], data[outcome]).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
    if (table.to_numpy() < MIN_CELL).any():
        return {**res, "suppressed": True, "note": "存在样本数小于 10 的格子，结果已抑制"}
    rate = lambda e: round(100 * table.loc[e, 1] / table.loc[e].sum(), 1)  # noqa: E731
    chi2, p, _, _ = sps.chi2_contingency(table.to_numpy())
    return {**res, "suppressed": False, "exposed_n": int(table.loc[1].sum()), "exposed_rate_pct": rate(1),
            "unexposed_n": int(table.loc[0].sum()), "unexposed_rate_pct": rate(0), "p": float(p),
            "note": "未调整混杂的粗比较"}


def screen_associations(df, exposures, outcome, population="全体", top_k=15):
    rows, suppressed = [], 0
    for e in exposures:
        if e == outcome or e in COVARIATES or e not in df.columns:
            continue
        r = logistic_regression(df, e, outcome, population)
        if r["suppressed"]:
            suppressed += 1
            continue
        rows.append({k: r[k] for k in ["exposure", "estimate", "ci_low", "ci_high", "p", "n", "unit"]})
    rows.sort(key=lambda r: r["p"])
    return {"method": "screen_associations", "outcome": outcome, "population": _population(df, outcome, population)[1],
            "n_tested": len(rows) + suppressed, "n_suppressed": suppressed, "top": rows[:top_k],
            "note": "逐个字段做调整混杂的 logistic 回归，按 p 值排序；这是探索集上的筛查，不是结论"}


METHODS = {"logistic_regression": "logistic 回归（OR）", "cox_regression": "Cox 回归（HR）",
           "propensity_matching": "倾向评分匹配（OR）"}


def run_method(df, method, exposure, outcome, population="全体"):
    if method == "logistic_regression":
        return logistic_regression(df, exposure, outcome, population)
    if method == "cox_regression":
        return cox_regression(df, exposure, population)
    if method == "propensity_matching":
        return propensity_matching(df, exposure, outcome, population)
    raise ValueError(f"未知的分析方法：{method}")


__all__ = ["OUTCOMES", "POPULATIONS", "METHODS", "logistic_regression", "cox_regression", "propensity_matching",
           "describe", "compare_groups", "screen_associations", "run_method", "is_binary"]
