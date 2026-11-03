"""组学模块（预留）。

启用条件：数据字典中声明了「14_基因与组学」模块的字段，且数据中这些字段确实有值（不根据列名猜测）。
未启用时研究循环行为完全不变。启用后，在数据发现阶段对每个组学字段做调整混杂的 logistic 回归，
把显著的结果作为额外的表型发现，随后与其他发现一样经过文献检索、假设生成、审稿、登记与验证。
第一版只提供这一最简实现，具体组学分析方法留待拿到组学数据后再定。
"""

from __future__ import annotations

import pandas as pd

from . import stats_tools as st


def active_fields(dictionary, df: pd.DataFrame) -> list[str]:
    declared = dictionary.omics_fields()
    return [f for f in declared if f in df.columns and df[f].notna().any()]


def status(dictionary, df: pd.DataFrame) -> dict:
    declared = dictionary.omics_fields()
    active = active_fields(dictionary, df)
    if not declared:
        reason = "数据字典中没有声明「基因与组学」模块"
    elif not active:
        reason = "数据字典声明了组学字段，但数据中这些字段没有值"
    else:
        reason = f"检测到 {len(active)} 个有值的组学字段"
    return {"enabled": bool(active), "fields": active, "reason_zh": reason}


def findings(df: pd.DataFrame, fields: list[str], tested: set[str], p_max: float = 1e-3) -> list[dict]:
    out = []
    for f in fields:
        if f"{f}|dry_eye_confirmed" in tested:
            continue
        r = st.logistic_regression(df, f, "dry_eye_confirmed", "全体")
        if not r["suppressed"] and r["p"] < p_max:
            out.append({"exposure": f, "outcome": "dry_eye_confirmed", "population": "全体", "source": "组学模块",
                        "summary_zh": f"组学模块：{f} 与干眼相关（OR={r['estimate']:.2f}，p={r['p']:.1e}）"})
    return out
