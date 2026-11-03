"""依据数据字典生成合成数据，并植入已知信号，用来检验研究循环本身。

合成数据里的「患者」全部是虚构的。植入信号清单单独保存，研究循环运行期间不读取它，
只在运行结束后用于评测（找回率、假信号数）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# 植入信号：exposure 对 outcome 的真实效应（对数 OR；连续变量为每 1 个标准差）
PLANTED_SIGNALS = [
    {"exposure": "sjogren_syndrome", "outcome": "dry_eye_aqueous_deficient", "log_or": 2.0, "kind": "共识A级"},
    {"exposure": "sjogren_syndrome", "outcome": "dry_eye_confirmed", "log_or": 1.5, "kind": "共识A级"},
    {"exposure": "mgd", "outcome": "dry_eye_lipid_deficient", "log_or": 1.8, "kind": "共识A级"},
    {"exposure": "diabetes_mellitus", "outcome": "dry_eye_confirmed", "log_or": 0.6, "kind": "共识A级"},
    {"exposure": "antidepressant_exposure", "outcome": "dry_eye_confirmed", "log_or": 0.7, "kind": "共识A级"},
    {"exposure": "preserved_eye_drop_exposure", "outcome": "dry_eye_confirmed", "log_or": 0.6, "kind": "共识A级"},
    {"exposure": "dyslipidemia", "outcome": "dry_eye_lipid_deficient", "log_or": 0.9, "kind": "新信号"},
    {"exposure": "crp_mg_l", "outcome": "dry_eye_confirmed", "log_or": 0.35, "kind": "新信号"},
]
# 与干眼无关的字段。chronic_kidney_disease 只通过眼科就诊次数与干眼「相关」，调整混杂后应为阴性。
NULL_FIELDS = ["chronic_kidney_disease", "hypertension", "parkinson_disease", "malignancy_any"]
OMICS_SIGNALS = [{"exposure": "tear_il6_pg_ml", "outcome": "dry_eye_confirmed", "log_or": 0.5, "kind": "组学新信号"}]
OMICS_NULL_FIELDS = ["tear_il17a_pg_ml"]

PREVALENCE = {
    "sjogren_syndrome": 0.03, "rheumatoid_arthritis": 0.04, "stevens_johnson_syndrome": 0.004, "gvhd": 0.005,
    "thyroid_dysfunction": 0.07, "diabetes_mellitus": 0.12, "anxiety_disorder": 0.10, "depression": 0.09,
    "sleep_disorder": 0.18, "mgd": 0.25, "blepharitis": 0.12, "chemotherapy_exposure": 0.02,
    "contact_lens_long_term": 0.12, "antihistamine_exposure": 0.10, "anxiolytic_exposure": 0.06,
    "isotretinoin_exposure": 0.01, "antiglaucoma_drug_exposure": 0.05, "preserved_eye_drop_exposure": 0.15,
    "corneal_surgery_history": 0.04, "prolonged_screen_use": 0.35, "dyslipidemia": 0.20,
    "chronic_kidney_disease": 0.06, "parkinson_disease": 0.01, "malignancy_any": 0.04,
}
NO_MISSING = {"sjogren_syndrome", "mgd"}


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _z(x):
    return (x - x.mean()) / x.std()


def generate(n: int = 20_000, seed: int = 20261103, with_omics: bool = False):
    """返回 (patients DataFrame, 植入信号清单)。"""
    rng = np.random.default_rng(seed)
    b = lambda p: (rng.random(n) < p).astype(int)  # noqa: E731
    age = np.clip(rng.normal(52, 14, n), 18, 90).round()
    female = b(0.56)
    df = pd.DataFrame({"patient_id": [f"P{i:06d}" for i in range(n)], "age_at_index": age,
                       "sex": np.where(female == 1, "F", "M")})
    for name, p in PREVALENCE.items():
        df[name] = b(p)
    df["antidepressant_exposure"] = np.where(df["depression"] == 1, b(0.6), b(0.02))
    df["type2_diabetes"] = df["diabetes_mellitus"] * b(0.9)
    df["hypertension"] = b(_sigmoid(-2.2 + 0.05 * (age - 52)))
    df["antihypertensive_exposure"] = df["hypertension"] * b(0.8)
    df["cataract_surgery_history"] = b(_sigmoid(-3.0 + 0.06 * (age - 52)))
    smoking = rng.choice(["never", "former", "current"], n, p=[0.6, 0.2, 0.2])
    df["smoking_status"] = smoking
    df["oph_visit_count_pre_365d"] = rng.poisson(1.2 + 1.8 * df["chronic_kidney_disease"]
                                                 + 0.8 * df["antiglaucoma_drug_exposure"])
    df["hba1c_pct"] = np.where(df["diabetes_mellitus"] == 1, rng.normal(7.6, 1.2, n), rng.normal(5.4, 0.4, n)).round(1)
    df["crp_mg_l"] = np.exp(rng.normal(0.5, 0.9, n)).round(2)
    lp = (-2.0 + 0.025 * (age - 52) + 0.45 * female + 0.30 * df["oph_visit_count_pre_365d"]
          + 1.5 * df["sjogren_syndrome"] + 0.6 * df["diabetes_mellitus"] + 0.7 * df["antidepressant_exposure"]
          + 0.6 * df["preserved_eye_drop_exposure"] + 0.35 * _z(df["crp_mg_l"]))
    manifest = [dict(s) for s in PLANTED_SIGNALS]
    if with_omics:
        df["tear_il6_pg_ml"] = np.exp(rng.normal(2.0, 0.6, n)).round(2)
        df["tear_il17a_pg_ml"] = np.exp(rng.normal(1.5, 0.5, n)).round(2)
        lp = lp + 0.5 * _z(df["tear_il6_pg_ml"])
        manifest += [dict(s) for s in OMICS_SIGNALS]
    case = (rng.random(n) < _sigmoid(lp)).astype(int)
    df["dry_eye_confirmed"] = case
    aq = b(_sigmoid(-1.0 + 2.0 * df["sjogren_syndrome"] + 0.3 * female))
    lip = b(_sigmoid(-0.3 + 1.8 * df["mgd"] + 0.9 * df["dyslipidemia"]))
    for name, values in [("dry_eye_aqueous_deficient", aq), ("dry_eye_lipid_deficient", lip),
                         ("dry_eye_mixed", aq * lip)]:
        df[name] = pd.array(np.where(case == 1, values, 0), dtype="Int64")
        df.loc[case == 0, name] = pd.NA
    sev = rng.choice(["轻度", "中度", "重度"], n, p=[0.5, 0.35, 0.15])
    df["dry_eye_severity"] = np.where(case == 1, sev, None)
    for s in ["symptom_dryness", "symptom_burning", "symptom_foreign_body", "symptom_eye_fatigue"]:
        df[s] = np.where(case == 1, b(0.8), b(0.15))
    for eye in ["od", "os"]:
        df[f"fbut_{eye}_sec"] = np.clip(np.where(case == 1, rng.normal(4.5, 1.8, n), rng.normal(10, 2.5, n)), 0.5, 20).round(1)
        df[f"schirmer1_{eye}_mm5min"] = np.clip(np.where(case == 1, rng.normal(6 - 3 * aq, 3, n), rng.normal(14, 5, n)), 0, 35).round()
        df[f"corneal_fluorescein_score_{eye}"] = np.where(case == 1, rng.poisson(3, n), rng.poisson(0.5, n))
        df[f"meibomian_expressibility_{eye}"] = np.clip(rng.poisson(0.6 + 1.5 * df["mgd"]), 0, 3)
    start = pd.Timestamp("2018-01-01") + pd.to_timedelta(rng.integers(0, 5 * 365, n), unit="D")
    follow = rng.integers(365, 6 * 365, n)
    t = (rng.uniform(0.05, 0.95, n) * follow).astype(int)
    df["first_oph_visit_date"] = start
    df["followup_end_date"] = start + pd.to_timedelta(follow, unit="D")
    idx = start + pd.to_timedelta(t, unit="D")
    df["dry_eye_index_date"] = pd.Series(idx).where(case == 1)
    df["first_dry_eye_diagnosis_date"] = df["dry_eye_index_date"]
    # 0=明确否认，1=明确存在，NA=未记录：布尔暴露随机缺失约 12%
    for name in list(PREVALENCE) + ["antidepressant_exposure", "type2_diabetes", "hypertension",
                                    "antihypertensive_exposure", "cataract_surgery_history"]:
        col = pd.array(df[name].to_numpy(), dtype="Int64")
        if name not in NO_MISSING:
            col[rng.random(n) < 0.12] = pd.NA
        df[name] = col
    for name in ["fbut_od_sec", "fbut_os_sec", "schirmer1_od_mm5min", "schirmer1_os_mm5min", "hba1c_pct"]:
        df.loc[rng.random(n) < 0.15, name] = np.nan
    for name in NULL_FIELDS:
        manifest.append({"exposure": name, "outcome": "*", "log_or": 0.0, "kind": "无关字段"})
    if with_omics:
        for name in OMICS_NULL_FIELDS:
            manifest.append({"exposure": name, "outcome": "*", "log_or": 0.0, "kind": "无关字段"})
    return df, manifest


def write(out_dir: Path, manifest_path: Path, n: int = 20_000, seed: int = 20261103, with_omics: bool = False) -> Path:
    df, manifest = generate(n=n, seed=seed, with_omics=with_omics)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "patients.parquet", index=False)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir
