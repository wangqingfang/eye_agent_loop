"""加载《干眼共病模型数据字典》。研究循环用到的字段定义都来自这里。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .errors import ConfigError

OUTCOMES = {
    "dry_eye_confirmed": "干眼明确诊断",
    "dry_eye_aqueous_deficient": "水液缺乏型干眼",
    "dry_eye_lipid_deficient": "脂质异常型干眼",
    "dry_eye_mixed": "混合型干眼",
}
# 干眼分型只在干眼患者中有意义
CASE_ONLY_OUTCOMES = {"dry_eye_aqueous_deficient", "dry_eye_lipid_deficient", "dry_eye_mixed"}
COVARIATES = ["age_at_index", "sex", "oph_visit_count_pre_365d"]
EXPOSURE_MODULE_PREFIXES = tuple(f"{i:02d}_" for i in range(4, 15))
OMICS_MODULE_PREFIX = "14_"
EXPOSURE_TYPES = {"bool", "numeric", "integer"}


@dataclass(frozen=True)
class Field:
    name: str
    zh: str
    module: str
    dtype: str
    evidence: str
    priority: str
    role: str
    keywords: str


class DataDictionary:
    def __init__(self, fields: dict[str, Field], aliases: dict[str, str]):
        self.fields = fields
        self._aliases = aliases

    @classmethod
    def load(cls, path: Path) -> "DataDictionary":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"找不到数据字典文件：{path}。请确认「资料」文件夹完整。")
        sheet = pd.read_excel(path, sheet_name="字段字典")
        fields: dict[str, Field] = {}
        for _, row in sheet.iterrows():
            name = str(row.get("英文变量名", "")).strip()
            if not name or name == "nan":
                continue
            fields[name] = Field(
                name=name,
                zh=str(row.get("中文字段名", name)),
                module=str(row.get("一级模块", "")),
                dtype=str(row.get("数据类型", "")).strip(),
                evidence=str(row.get("证据等级", "")),
                priority=str(row.get("V1优先级", "")),
                role=str(row.get("模型角色", "")),
                keywords=str(row.get("标准实体/关键词", "")),
            )
        aliases: dict[str, str] = {}
        try:
            entities = pd.read_excel(path, sheet_name="共病实体词典")
            for _, row in entities.iterrows():
                key = str(row.get("标准英文实体", "")).strip()
                alias = str(row.get("别名/提示词", ""))
                english = [a.strip() for a in alias.split(";") if re.search(r"[A-Za-z]{3,}", a)]
                if key and english:
                    aliases[key] = english[0]
        except ValueError:
            pass
        return cls(fields, aliases)

    def zh(self, name: str) -> str:
        if name in OUTCOMES:
            return OUTCOMES[name]
        field = self.fields.get(name)
        return field.zh if field else name

    def evidence(self, name: str) -> str:
        field = self.fields.get(name)
        return field.evidence if field else ""

    def is_exposure(self, name: str) -> bool:
        field = self.fields.get(name)
        return bool(field and field.module.startswith(EXPOSURE_MODULE_PREFIXES) and field.dtype in EXPOSURE_TYPES)

    def exposures_in(self, columns) -> list[str]:
        return [c for c in columns if self.is_exposure(c)]

    def omics_fields(self) -> list[str]:
        return [f.name for f in self.fields.values() if f.module.startswith(OMICS_MODULE_PREFIX)]

    def search_term(self, name: str) -> str:
        """把字段名转成英文检索词，用于文献检索。"""
        if name in self._aliases:
            return self._aliases[name]
        base = re.sub(r"_(exposure|history|use|disorder|status|pct|mg_l|long_term|any)$", "", name)
        base = base.replace("_drug", "").replace("_", " ")
        return {
            "mgd": "meibomian gland dysfunction",
            "gvhd": "graft-versus-host disease",
            "dry eye confirmed": "dry eye disease",
            "dry eye aqueous deficient": "aqueous deficient dry eye",
            "dry eye lipid deficient": "evaporative dry eye meibomian",
            "dry eye mixed": "mixed dry eye",
            "crp": "C-reactive protein",
            "hba1c": "HbA1c glycated hemoglobin",
            "preserved eye drop": "preservative eye drops benzalkonium",
            "prolonged screen": "screen time digital device",
        }.get(base, base)

    def catalog(self, columns) -> list[dict]:
        """给 LLM 看的字段目录：只有定义，没有任何数据。"""
        rows = []
        for name in self.exposures_in(columns):
            f = self.fields[name]
            rows.append({"字段": name, "中文": f.zh, "模块": f.module, "类型": f.dtype, "证据等级": f.evidence})
        return rows
