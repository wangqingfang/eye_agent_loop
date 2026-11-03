"""外部来源接口：Europe PMC、PubMed、ClinicalTrials.gov、Open Targets。

所有结果按来源与查询词缓存在本地（同一查询不重复下载、重跑结果一致）。
某个来源请求失败时记录失败并返回空结果，不中断研究轮次。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
from pathlib import Path

import requests

UA = {"User-Agent": "agentloop/0.1 (dry-eye comorbidity research loop)"}
TIMEOUT = 25


class Cache:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str, key: str) -> Path:
        return self.dir / f"{source}_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"

    def get(self, source, key):
        p = self._path(source, key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, source, key, value):
        self._path(source, key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _get(url, **kw):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(1 + attempt)
    raise last or RuntimeError("请求失败")


def _clip(text, n):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:n]


class OnlineSources:
    """真实的外部来源。"""

    name = "online"

    def __init__(self, cache: Cache, ncbi_api_key: str = ""):
        self.cache = cache
        self.ncbi_api_key = ncbi_api_key
        self.failures: list[dict] = []

    def _cached(self, source, key, fetch):
        hit = self.cache.get(source, key)
        if hit is not None:
            return hit
        try:
            value = fetch()
        except Exception as exc:  # 网络、格式变化等：记录后继续
            self.failures.append({"source": source, "query": key, "error": f"{type(exc).__name__}: {exc}"[:300]})
            return []
        self.cache.put(source, key, value)
        return value

    # ---- 文献 ----
    def europe_pmc(self, query, limit=8):
        year = _dt.date.today().year

        def fetch():
            q = f"({query}) AND SRC:MED AND PUB_YEAR:[{year - 10} TO {year}]"
            r = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                     params={"query": q, "format": "json", "pageSize": limit, "resultType": "core"})
            out = []
            for it in r.json().get("resultList", {}).get("result", []):
                if not it.get("pmid"):
                    continue
                out.append({"id": str(it["pmid"]), "pmid": str(it["pmid"]), "pmcid": it.get("pmcid"),
                            "title": _clip(it.get("title"), 300), "year": it.get("pubYear"),
                            "journal": it.get("journalTitle") or it.get("journalInfo", {}).get("journal", {}).get("title"),
                            "abstract": _clip(it.get("abstractText"), 1200),
                            "open_access": it.get("isOpenAccess") == "Y", "source": "Europe PMC"})
            return out
        return self._cached("europepmc", f"{query}|{limit}", fetch)

    def pubmed(self, query, limit=8):
        def fetch():
            base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
            params = {"db": "pubmed", "term": query, "retmax": limit, "retmode": "json", "sort": "relevance",
                      "tool": "agentloop", "email": "agentloop@example.org"}
            if self.ncbi_api_key:
                params["api_key"] = self.ncbi_api_key
            r = _get(base + "esearch.fcgi", params=params, allow_redirects=False)
            if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                raise RuntimeError(f"PubMed 拒绝了请求（HTTP {r.status_code}）")
            ids = r.json()["esearchresult"].get("idlist", [])
            if not ids:
                return []
            s = _get(base + "esummary.fcgi", params={**params, "id": ",".join(ids)}).json()["result"]
            return [{"id": i, "pmid": i, "pmcid": None, "title": _clip(s[i].get("title"), 300),
                     "year": (s[i].get("pubdate") or "")[:4], "journal": s[i].get("fulljournalname"),
                     "abstract": "", "open_access": False, "source": "PubMed"} for i in ids if i in s]
        return self._cached("pubmed", f"{query}|{limit}", fetch)

    def fulltext(self, pmcid):
        def fetch():
            r = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
            body = r.text.split("<body", 1)[-1]
            return [{"pmcid": pmcid, "text": _clip(body, 3000)}]
        hit = self._cached("fulltext", pmcid, fetch)
        return hit[0]["text"] if hit else ""

    def trials(self, query, limit=5):
        def fetch():
            r = _get("https://clinicaltrials.gov/api/v2/studies",
                     params={"query.term": query, "pageSize": limit,
                             "fields": "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName"})
            out = []
            for s in r.json().get("studies", []):
                p = s.get("protocolSection", {})
                out.append({"id": p.get("identificationModule", {}).get("nctId"),
                            "title": p.get("identificationModule", {}).get("briefTitle"),
                            "status": p.get("statusModule", {}).get("overallStatus"),
                            "phase": ",".join(p.get("designModule", {}).get("phases", []) or []),
                            "interventions": [i.get("name") for i in p.get("armsInterventionsModule", {}).get("interventions", [])][:5],
                            "source": "ClinicalTrials.gov"})
            return out
        return self._cached("ctgov", f"{query}|{limit}", fetch)

    # ---- Open Targets ----
    def _ot(self, query, variables):
        r = requests.post("https://api.platform.opentargets.org/api/v4/graphql", headers=UA, timeout=TIMEOUT,
                          json={"query": query, "variables": variables})
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message", "Open Targets 返回错误"))
        return data["data"]

    def _ot_search(self, text, entity):
        q = "query($q:String!,$e:[String!]){search(queryString:$q,entityNames:$e,page:{index:0,size:1}){hits{id name}}}"
        hits = self._ot(q, {"q": text, "e": [entity]})["search"]["hits"]
        return hits[0] if hits else None

    def disease_targets(self, disease, limit=10):
        def fetch():
            hit = self._ot_search(disease, "disease")
            if not hit:
                return []
            q = ("query($id:String!,$n:Int!){disease(efoId:$id){name associatedTargets(page:{index:0,size:$n})"
                 "{rows{score target{id approvedSymbol approvedName}}}}}")
            rows = self._ot(q, {"id": hit["id"], "n": limit})["disease"]["associatedTargets"]["rows"]
            return [{"id": f"OT:{hit['id']}:{r['target']['approvedSymbol']}", "disease": hit["name"],
                     "disease_id": hit["id"], "symbol": r["target"]["approvedSymbol"],
                     "target_name": r["target"]["approvedName"], "score": round(r["score"], 3),
                     "source": "Open Targets"} for r in rows]
        return self._cached("ot_disease", f"{disease}|{limit}", fetch)

    def target_drugs(self, symbol, limit=8):
        def fetch():
            hit = self._ot_search(symbol, "target")
            if not hit:
                return []
            q = ("query($id:String!){target(ensemblId:$id){approvedSymbol drugAndClinicalCandidates"
                 "{rows{maxClinicalStage drug{id name}}}}}")
            t = self._ot(q, {"id": hit["id"]})["target"]
            rows = (t.get("drugAndClinicalCandidates") or {}).get("rows", [])[:limit]
            return [{"id": f"OT:{t['approvedSymbol']}:{r['drug']['id']}", "symbol": t["approvedSymbol"],
                     "drug": r["drug"]["name"], "stage": r.get("maxClinicalStage"), "source": "Open Targets"}
                    for r in rows]
        return self._cached("ot_target", f"{symbol}|{limit}", fetch)
