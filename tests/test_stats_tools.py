"""次接缝：统计工具层。用已知效应量的生成数据直接调用各工具。"""

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from agentloop import stats_tools as st
from agentloop.registry import FDRLedger


def _cohort(n=20000, log_or=np.log(2.0), seed=1, continuous=False):
    rng = np.random.default_rng(seed)
    age = rng.normal(50, 10, n)
    female = rng.random(n) < 0.5
    visits = rng.poisson(1.5, n)
    x = rng.normal(0, 1, n) if continuous else (rng.random(n) < 0.3).astype(int)
    lp = -1.5 + 0.02 * (age - 50) + 0.3 * female + 0.2 * visits + log_or * x
    y = (rng.random(n) < 1 / (1 + np.exp(-lp))).astype(int)
    return pd.DataFrame({"patient_id": [f"P{i:06d}" for i in range(n)], "age_at_index": age,
                         "sex": np.where(female, "F", "M"), "oph_visit_count_pre_365d": visits,
                         "x": x, "dry_eye_confirmed": y})


def test_logistic_recovers_known_or_with_default_covariates():
    r = st.logistic_regression(_cohort(), "x", "dry_eye_confirmed")
    assert r["covariates"] == ["age_at_index", "sex", "oph_visit_count_pre_365d"]
    assert r["ci_low"] < 2.0 < r["ci_high"] and abs(r["estimate"] - 2.0) < 0.2


def test_continuous_exposure_is_per_standard_deviation():
    df = _cohort(log_or=0.4, continuous=True)
    df["x"] = df["x"] * 7 + 100  # 换单位不影响每 SD 的效应
    r = st.logistic_regression(df, "x", "dry_eye_confirmed")
    assert r["unit"] == "每增加 1 个标准差" and abs(np.log(r["estimate"]) - 0.4) < 0.06


def test_confounder_adjustment_removes_spurious_association():
    rng = np.random.default_rng(3)
    df = _cohort(log_or=0.0)
    df["z"] = (rng.random(len(df)) < 0.05 + 0.08 * df["oph_visit_count_pre_365d"].clip(0, 5)).astype(int)
    crude = st.compare_groups(df, "z", "dry_eye_confirmed")
    adj = st.logistic_regression(df, "z", "dry_eye_confirmed")
    assert crude["exposed_rate_pct"] > crude["unexposed_rate_pct"]
    assert adj["ci_low"] < 1 < adj["ci_high"]


def test_small_groups_are_suppressed_not_dropped_silently():
    df = _cohort(n=3000)
    df["rare"] = 0
    df.loc[:4, "rare"] = 1
    r = st.logistic_regression(df, "rare", "dry_eye_confirmed")
    assert r["suppressed"] and r["estimate"] is None and "已抑制" in r["note"]
    d = st.describe(df, ["rare"])
    assert d["fields"][0]["n_yes"] == st.SUPPRESSED
    assert st.compare_groups(df, "rare", "dry_eye_confirmed")["suppressed"]


def test_missing_is_not_treated_as_zero():
    df = _cohort(n=5000)
    df["x"] = df["x"].astype("Int64")
    df.loc[:999, "x"] = pd.NA
    assert st.logistic_regression(df, "x", "dry_eye_confirmed")["n"] == 4000


def test_cox_recovers_hazard_ratio_with_censoring():
    rng = np.random.default_rng(7)
    n = 8000
    x = (rng.random(n) < 0.4).astype(int)
    t_event = rng.exponential(1000 / np.exp(np.log(2.0) * x))
    t_cens = rng.uniform(200, 1500, n)
    event = (t_event <= t_cens).astype(int)
    start = pd.Timestamp("2020-01-01")
    df = pd.DataFrame({"age_at_index": rng.normal(50, 10, n), "sex": rng.choice(["F", "M"], n),
                       "oph_visit_count_pre_365d": rng.poisson(1, n), "x": x, "dry_eye_confirmed": event,
                       "first_oph_visit_date": start,
                       "followup_end_date": start + pd.to_timedelta(t_cens.astype(int) + 1, unit="D")})
    df["dry_eye_index_date"] = (start + pd.to_timedelta(np.minimum(t_event, t_cens).astype(int) + 1, unit="D")).where(event == 1)
    r = st.cox_regression(df, "x")
    assert r["ci_low"] < 2.0 < r["ci_high"]


def test_propensity_matching_estimates_effect():
    r = st.propensity_matching(_cohort(), "x", "dry_eye_confirmed")
    assert r["n_pairs"] > 1000 and r["ci_low"] < 2.0 < r["ci_high"]


def test_fdr_ledger_matches_reference_and_accumulates(tmp_path):
    ps = [0.001, 0.02, 0.04, 0.3, 0.0004]
    ledger = FDRLedger(tmp_path)
    for i, p in enumerate(ps):
        ledger.add(f"H{i}", 1 + i // 2, p)
    _, ref, _, _ = multipletests(ps, method="fdr_bh")
    q = ledger.q_values()
    assert np.allclose([q[f"H{i}"] for i in range(len(ps))], ref)
    assert FDRLedger(tmp_path).n_tests() == 5  # 持久化，跨轮次累计
