"""运行编排：驱动研究轮次与阶段、写检查点、判断停止条件、支持断点恢复。"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from . import evaluation, omics, report, synthetic, word_export
from .data_access import DataAccess
from .dictionary import DataDictionary
from .errors import BudgetExceeded, UserFacingError
from .llm import GuardedLLM
from .registry import FDRLedger, Registry
from .stages import RUNNERS, STAGE_ZH, STAGES, Env, discovery

NO_PROGRESS_LIMIT = 2


class Interrupted(Exception):
    """测试用：模拟在某个阶段之后中断。"""


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stage_path(run_dir: Path, round_no: int, stage: str) -> Path:
    return run_dir / "rounds" / f"r{round_no}" / f"{STAGES.index(stage) + 1}_{stage}.json"


def conclusions(registry: Registry, ledger: FDRLedger) -> list[dict]:
    """所有已验证假设的当前结论。有意义结论由代码判定，不由 LLM 宣布。"""
    q = ledger.q_values()
    out = []
    for r in registry.results():
        h = registry.get(r["hypothesis_id"])
        qv = q.get(r["hypothesis_id"])
        meaningful = bool(not r["suppressed"] and qv is not None and qv < ledger.alpha and r["direction_ok"])
        out.append({"hypothesis": h, "result": r, "q": qv, "meaningful": meaningful})
    return out


def new_run(project_dir: Path, config, data_dir: Path | None, synthetic_n: int = 20_000, with_omics: bool = False,
            llm_mode: str = "online", sources_mode: str = "online", split_salt: str | None = None) -> Path:
    run_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(project_dir) / "runs" / run_id
    while run_dir.exists():
        run_id += "x"
        run_dir = Path(project_dir) / "runs" / run_id
    run_dir.mkdir(parents=True)
    is_synthetic = data_dir is None
    if is_synthetic:
        data_dir = run_dir / "synthetic_data"
        synthetic.write(data_dir, run_dir / "evaluation" / "植入信号清单.json", n=synthetic_n, with_omics=with_omics)
    state = {"run_id": run_id, "created": _dt.datetime.now().isoformat(timespec="seconds"),
             "data_dir": str(Path(data_dir).resolve()), "synthetic": is_synthetic, "config": config.snapshot(),
             "llm_mode": llm_mode, "sources_mode": sources_mode, "split_salt": split_salt or run_id,
             "round": 1, "stage_index": 0,
             "rounds": [], "no_progress_streak": 0, "tokens_total": 0, "status": "running", "stop_reason": ""}
    _write_json(run_dir / "state.json", state)
    return run_dir


def latest_unfinished(project_dir: Path) -> Path | None:
    runs = Path(project_dir) / "runs"
    if not runs.exists():
        return None
    for d in sorted((p for p in runs.iterdir() if (p / "state.json").exists()), reverse=True):
        if _read_json(d / "state.json")["status"] != "completed":
            return d
    return None


def _previous(run_dir: Path, state: dict, registry: Registry, ledger: FDRLedger) -> dict:
    tested = []
    for r in range(1, state["round"]):
        p = stage_path(run_dir, r, "discovery")
        if p.exists():
            tested += [f"{f['exposure']}|{f['outcome']}" for f in _read_json(p)["findings"]]
    meaningful = [{"statement_zh": c["hypothesis"]["statement_zh"], "exposure": c["hypothesis"]["exposure"],
                   "outcome": c["hypothesis"]["outcome"], "estimate": c["result"]["estimate"]}
                  for c in conclusions(registry, ledger) if c["meaningful"]]
    return {"tested": tested, "meaningful": meaningful}


def run(run_dir: Path, config, backend, sources, progress=print, stop_after_stages: int | None = None) -> dict:
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json")
    dictionary = DataDictionary.load(config.data_dictionary)
    data = DataAccess(Path(state["data_dir"]), run_dir, salt=state.get("split_salt", state["run_id"]))
    registry, ledger = Registry(run_dir), FDRLedger(run_dir)
    omics_status = omics.status(dictionary, data.exploration())
    state["omics"] = omics_status
    llm = GuardedLLM(backend, data.sensitive_tokens, budget=config.token_budget, used_before_session=state["tokens_total"])
    env = Env(dictionary=dictionary, data=data, registry=registry, ledger=ledger, llm=llm, sources=sources,
              omics_fields=omics_status["fields"])
    state["status"], state["stop_reason"], state["split"] = "running", "", data.split_sizes()
    _write_json(run_dir / "state.json", state)
    done_this_session = 0
    try:
        while state["status"] == "running":
            r = state["round"]
            outputs = {s: _read_json(stage_path(run_dir, r, s)) for s in STAGES[: state["stage_index"]]}
            for i in range(state["stage_index"], len(STAGES)):
                stage = STAGES[i]
                llm.check_budget()
                progress(f"第 {r} 轮 · 正在{STAGE_ZH[stage]}……")
                if stage == "discovery":
                    out = discovery(env, r, _previous(run_dir, state, registry, ledger))
                else:
                    out = RUNNERS[stage](env, r, outputs)
                outputs[stage] = out
                _write_json(stage_path(run_dir, r, stage), out)
                state["stage_index"], state["tokens_total"] = i + 1, llm.total_used
                _write_json(run_dir / "state.json", state)
                done_this_session += 1
                if stop_after_stages is not None and done_this_session >= stop_after_stages:
                    raise Interrupted()
            _finish_round(run_dir, state, registry, ledger, outputs, config, progress)
    except BudgetExceeded:
        state.update(status="paused", stop_reason="本次启动的 token 预算已用完，进度已保存，可选择「继续上次的研究」")
        progress("token 预算已用完，进度已保存。")
    state["tokens_total"] = llm.total_used
    _write_json(run_dir / "state.json", state)
    render(run_dir, config)
    return state


def _finish_round(run_dir, state, registry, ledger, outputs, config, progress):
    r = state["round"]
    all_c = conclusions(registry, ledger)
    new = [c["hypothesis"]["id"] for c in all_c if c["meaningful"] and c["hypothesis"]["round"] == r]
    state["rounds"].append({
        "round": r, "n_findings": len(outputs["discovery"]["findings"]),
        "n_hypotheses": len(outputs["hypothesis"]["hypotheses"]), "n_passed_review": len(outputs["review"]["passed"]),
        "n_validated": len(outputs["validate"]["results"]), "new_meaningful": new,
        "cumulative_meaningful": sum(c["meaningful"] for c in all_c), "tokens_total": state["tokens_total"]})
    state["no_progress_streak"] = 0 if new else state["no_progress_streak"] + 1
    progress(f"第 {r} 轮完成：新增有意义结论 {len(new)} 条。")
    if r >= config.max_rounds:
        state.update(status="completed", stop_reason=f"已跑满最大轮数（{config.max_rounds} 轮）")
    elif state["no_progress_streak"] >= NO_PROGRESS_LIMIT:
        state.update(status="completed", stop_reason=f"连续 {NO_PROGRESS_LIMIT} 轮没有新的有意义结论")
    else:
        state["round"], state["stage_index"] = r + 1, 0
    _write_json(run_dir / "state.json", state)
    render(run_dir, config)


def render(run_dir: Path, config) -> Path:
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json")
    registry, ledger = Registry(run_dir), FDRLedger(run_dir)
    concl = conclusions(registry, ledger)
    rounds = {}
    for s in state["rounds"] + ([{"round": state["round"]}] if state["status"] != "completed" else []):
        r = s["round"]
        rounds[r] = {st: _read_json(stage_path(run_dir, r, st)) for st in STAGES if stage_path(run_dir, r, st).exists()}
    ev = None
    manifest = run_dir / "evaluation" / "植入信号清单.json"
    if state["synthetic"] and state["status"] == "completed" and manifest.exists():
        ev = evaluation.evaluate(_read_json(manifest), concl)
        _write_json(run_dir / "evaluation" / "评测结果.json", ev)
    path = report.write_html(run_dir, state, rounds, concl, ev, ledger.n_tests())
    try:
        word_export.write_docx(run_dir, state, rounds, concl, ev, ledger.n_tests())
    except Exception as exc:  # Word 导出失败不影响 HTML 报告
        (run_dir / "Word导出失败.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
    return path


__all__ = ["new_run", "run", "render", "latest_unfinished", "conclusions", "Interrupted", "UserFacingError"]
