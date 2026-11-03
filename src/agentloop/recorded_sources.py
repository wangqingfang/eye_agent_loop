"""离线来源：不联网，按查询词生成确定性的文献与靶点记录。

用于自动化测试和没有网络时的调试运行。生成的 PMID 以 9 开头、长度 8 位，标题注明「离线模拟文献」，
不会与真实文献混淆，报告中也会注明本次运行使用的是离线来源。
"""

from __future__ import annotations

import hashlib


def _num(text: str, mod: int) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest(), 16) % mod


class RecordedSources:
    name = "offline"

    def __init__(self, *_, **__):
        self.failures: list[dict] = []

    def europe_pmc(self, query, limit=8):
        n = 1 + _num(query, 4)
        return [{"id": str(90000000 + _num(f"{query}{i}", 9999999)), "pmid": str(90000000 + _num(f"{query}{i}", 9999999)),
                 "pmcid": f"PMC9{_num(query + str(i), 999999):06d}" if i == 0 else None,
                 "title": f"[离线模拟文献] {query} — study {i + 1}", "year": str(2016 + _num(query + str(i), 10)),
                 "journal": "Offline Journal", "abstract": f"Offline abstract about {query}.",
                 "open_access": i == 0, "source": "Europe PMC（离线模拟）"} for i in range(min(n, limit))]

    def pubmed(self, query, limit=8):
        return []

    def fulltext(self, pmcid):
        return f"Offline full text for {pmcid}."

    def trials(self, query, limit=5):
        return [{"id": f"NCT9{_num(query, 9999999):07d}", "title": f"[离线模拟试验] {query}", "status": "COMPLETED",
                 "phase": "PHASE2", "interventions": ["offline"], "source": "ClinicalTrials.gov（离线模拟）"}]

    def disease_targets(self, disease, limit=10):
        symbols = ["IL6", "TNF", "IL1B", "MMP9", "PPIA"][: max(1, min(limit, 5))]
        return [{"id": f"OT:OFFLINE:{s}", "disease": disease, "disease_id": "OFFLINE", "symbol": s,
                 "target_name": f"{s}（离线模拟）", "score": round(0.9 - 0.1 * i, 2), "source": "Open Targets（离线模拟）"}
                for i, s in enumerate(symbols)]

    def target_drugs(self, symbol, limit=8):
        return [{"id": f"OT:{symbol}:OFFLINEDRUG", "symbol": symbol, "drug": f"{symbol}-inhibitor（离线模拟）",
                 "stage": "PHASE_2", "source": "Open Targets（离线模拟）"}]
