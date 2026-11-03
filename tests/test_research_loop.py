"""主接缝：研究循环入口。用合成数据、离线规则引擎和离线来源端到端运行。"""

import json
import re

import pytest
from conftest import RecordingBackend, continue_run, read_jsonl, start

from agentloop.data_access import DataAccess
from agentloop.errors import ComplianceError, ValidationGateError
from agentloop.llm import GuardedLLM
from agentloop.registry import Registry

COUNT_KEYS = {"n", "n_exposed", "events", "n_yes", "n_pairs", "exposed_n", "unexposed_n", "n_recorded", "n_missing"}


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def test_llm_never_sees_patient_rows_or_small_cells(project):
    backend = RecordingBackend()
    run_dir, _, state = start(project, backend=backend)
    assert state["status"] == "completed"
    patient_ids = set(DataAccess(run_dir / "synthetic_data", run_dir, "fixed-salt").sensitive_tokens)
    for call in backend.calls:
        text = json.dumps(call["messages"], ensure_ascii=False)
        assert not (set(re.findall(r"P\d{6}", text)) & patient_ids)
        for m in call["messages"]:
            if m["role"] == "tool":
                for k, v in _walk(json.loads(m["content"])):
                    if k in COUNT_KEYS and isinstance(v, int) and k not in {"n_missing"}:
                        assert v >= 10, (k, v)


def test_guard_blocks_patient_identifier():
    llm = GuardedLLM(RecordingBackend(), {"P000123"}, budget=10_000)
    with pytest.raises(ComplianceError):
        llm.chat("discovery", [{"role": "user", "content": "患者 P000123 的记录"}])


def test_validation_set_is_gated(project):
    run_dir, _, state = start(project, stop_after=4, MAX_ROUNDS=1)  # 停在审稿之后、验证之前
    data = DataAccess(run_dir / "synthetic_data", run_dir, "fixed-salt")
    registry = Registry(run_dir)
    assert registry.all() == []
    with pytest.raises(ValidationGateError):
        data.open_validation("H1-1", registry, stage="validate")  # 未登记
    with pytest.raises(ValidationGateError):
        data.open_validation("H1-1", registry, stage="discovery")


def test_each_validation_read_is_for_a_registered_hypothesis(project, monkeypatch):
    seen = []
    original = DataAccess.open_validation

    def spy(self, hid, registry, stage):
        seen.append((hid, registry.is_registered(hid), stage))
        return original(self, hid, registry, stage)

    monkeypatch.setattr(DataAccess, "open_validation", spy)
    run_dir, _, _ = start(project, MAX_ROUNDS=1)
    assert seen and all(reg and stage == "validate" for _, reg, stage in seen)
    assert {h for h, _, _ in seen} == {r["hypothesis_id"] for r in read_jsonl(run_dir / "results.jsonl")}


def test_fabricated_citation_is_removed_and_reported(project):
    def inject(payload):
        payload["hypotheses"][0]["citations"].append("12345678")
        return payload

    run_dir, _, _ = start(project, backend=RecordingBackend(rewrite={"hypothesis": inject}), MAX_ROUNDS=1)
    out = json.loads((run_dir / "rounds/r1/3_hypothesis.json").read_text(encoding="utf-8"))
    assert any(x["citation"] == "12345678" for x in out["removed_citations"])
    assert all("12345678" not in h["citations"] for h in out["hypotheses"])
    html = (run_dir / "研究报告.html").read_text(encoding="utf-8")
    assert "12345678" in html and "已删除" in html


def test_registered_hypotheses_are_immutable(project):
    run_dir, _, _ = start(project, MAX_ROUNDS=1)
    registry = Registry(run_dir)
    assert registry.all() and registry.verify_unchanged()
    with pytest.raises(ValueError):
        registry.register(registry.all()[0])


def test_stops_at_max_rounds(project):
    _, _, state = start(project, MAX_ROUNDS=1)
    assert state["status"] == "completed" and "最大轮数" in state["stop_reason"]
    assert len(state["rounds"]) == 1


def test_stops_after_two_rounds_without_progress(project):
    backend = RecordingBackend(rewrite={"discovery": lambda p: {"findings": []}})
    _, _, state = start(project, backend=backend, MAX_ROUNDS=5)
    assert state["status"] == "completed" and "连续 2 轮" in state["stop_reason"]
    assert len(state["rounds"]) == 2


def test_budget_pauses_then_resume_finishes(project):
    run_dir, config, state = start(project, TOKEN_BUDGET=3000, MAX_ROUNDS=1)
    assert state["status"] == "paused" and "预算" in state["stop_reason"]
    for _ in range(10):  # 每次恢复按配置重新给一份预算，且至少完成一个阶段
        if state["status"] == "completed":
            break
        state = continue_run(run_dir, config)
    assert state["status"] == "completed"
