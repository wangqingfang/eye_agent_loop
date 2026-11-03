"""数据访问层：唯一能接触患者级数据的模块。

- 研究开始时按患者一次性划分探索集/验证集，划分结果保存后只读（ADR 0003）。
- 验证集只在「登记与验证」阶段、且只针对已登记的假设开放。
- 提供患者标识集合，供 LLM 接口做合规检查（ADR 0001）。
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pandas as pd

from .errors import DataError, ValidationGateError

REQUIRED_COLUMNS = ["patient_id", "age_at_index", "sex", "oph_visit_count_pre_365d", "dry_eye_confirmed"]
EXPLORATION, VALIDATION = "探索集", "验证集"


def load_patients(data_dir: Path) -> pd.DataFrame:
    data_dir = Path(data_dir)
    for name in ["patients.parquet", "patients.csv"]:
        path = data_dir / name
        if path.exists():
            df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
            break
    else:
        raise DataError(f"「{data_dir.name}」文件夹里没有找到 patients.parquet 或 patients.csv。"
                        "请技术同事按《使用说明》把数据转换成规定格式后放进去。")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError("数据缺少必需的列：" + "、".join(missing) + "。请技术同事按数据字典检查列名。")
    if df["patient_id"].duplicated().any():
        raise DataError("数据中有重复的 patient_id，每位患者只能有一行。请技术同事检查。")
    df["patient_id"] = df["patient_id"].astype(str)
    return df


class DataAccess:
    def __init__(self, data_dir: Path, run_dir: Path, salt: str):
        self._df = load_patients(data_dir)
        self.run_dir = Path(run_dir)
        self._split = self._load_or_create_split(salt)
        self.validation_access_log: list[dict] = []

    @property
    def columns(self) -> list[str]:
        return list(self._df.columns)

    @property
    def sensitive_tokens(self) -> set[str]:
        return set(self._df["patient_id"])

    def _load_or_create_split(self, salt: str) -> pd.Series:
        path = self.run_dir / "split.csv"
        if path.exists():
            saved = pd.read_csv(path, dtype={"patient_id": str})
            split = saved.set_index("patient_id")["set"]
            if set(split.index) != set(self._df["patient_id"]):
                raise DataError("数据与本次研究开始时不一致（患者名单变了）。不能在原研究上继续，请重新开始一次研究。")
            return split
        digest = self._df["patient_id"].map(lambda pid: hashlib.sha256(f"{salt}:{pid}".encode()).digest()[0])
        split = pd.Series(digest.map(lambda d: EXPLORATION if d % 2 == 0 else VALIDATION).to_numpy(),
                          index=self._df["patient_id"].to_numpy(), name="set")
        split.index.name = "patient_id"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        split.reset_index().to_csv(path, index=False)
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return split

    def _subset(self, which: str) -> pd.DataFrame:
        ids = self._split[self._split == which].index
        return self._df[self._df["patient_id"].isin(ids)].reset_index(drop=True).copy()

    def exploration(self) -> pd.DataFrame:
        return self._subset(EXPLORATION)

    def open_validation(self, hypothesis_id: str, registry, stage: str) -> pd.DataFrame:
        if stage != "validate":
            raise ValidationGateError(f"阶段「{stage}」试图读取验证集")
        if not registry.is_registered(hypothesis_id):
            raise ValidationGateError(f"假设 {hypothesis_id} 未登记，不能读取验证集")
        self.validation_access_log.append({"hypothesis_id": hypothesis_id, "stage": stage})
        return self._subset(VALIDATION)

    def split_sizes(self) -> dict:
        counts = self._split.value_counts()
        return {EXPLORATION: int(counts.get(EXPLORATION, 0)), VALIDATION: int(counts.get(VALIDATION, 0))}
