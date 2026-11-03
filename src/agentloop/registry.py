"""假设登记表与 FDR 账本。

- 登记后的假设只读：每个假设一个文件，写入后不可覆盖，并记录内容指纹。
- 验证结果以追加方式写入 results.jsonl。
- FDR 账本累计所有轮次的验证检验，统一做 Benjamini-Hochberg 校正（ADR 0003）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from statsmodels.stats.multitest import multipletests


def _fingerprint(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Registry:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir) / "registry"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.results_path = Path(run_dir) / "results.jsonl"

    def _path(self, hypothesis_id: str) -> Path:
        return self.dir / f"{hypothesis_id}.json"

    def register(self, hypothesis: dict) -> None:
        path = self._path(hypothesis["id"])
        if path.exists():
            raise ValueError(f"假设 {hypothesis['id']} 已登记，登记后不可修改")
        record = {"hypothesis": hypothesis, "fingerprint": _fingerprint(hypothesis)}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        path.chmod(0o444)

    def is_registered(self, hypothesis_id: str) -> bool:
        return self._path(hypothesis_id).exists()

    def get(self, hypothesis_id: str) -> dict:
        return json.loads(self._path(hypothesis_id).read_text(encoding="utf-8"))["hypothesis"]

    def all(self) -> list[dict]:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.dir.glob("*.json"))]
        return [r["hypothesis"] for r in records]

    def verify_unchanged(self) -> bool:
        for p in self.dir.glob("*.json"):
            record = json.loads(p.read_text(encoding="utf-8"))
            if _fingerprint(record["hypothesis"]) != record["fingerprint"]:
                return False
        return True

    def append_result(self, result: dict) -> None:
        with self.results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    def results(self) -> list[dict]:
        if not self.results_path.exists():
            return []
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def has_result(self, hypothesis_id: str) -> bool:
        return any(r["hypothesis_id"] == hypothesis_id for r in self.results())


class FDRLedger:
    def __init__(self, run_dir: Path, alpha: float = 0.05):
        self.path = Path(run_dir) / "fdr_ledger.json"
        self.alpha = alpha
        self.entries: list[dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def add(self, hypothesis_id: str, round_no: int, p: float) -> None:
        if any(e["hypothesis_id"] == hypothesis_id for e in self.entries):
            return
        self.entries.append({"hypothesis_id": hypothesis_id, "round": round_no, "p": p})
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def q_values(self) -> dict[str, float]:
        if not self.entries:
            return {}
        _, q, _, _ = multipletests([e["p"] for e in self.entries], alpha=self.alpha, method="fdr_bh")
        return {e["hypothesis_id"]: float(v) for e, v in zip(self.entries, q)}

    def n_tests(self) -> int:
        return len(self.entries)
