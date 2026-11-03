"""主接缝（续）：断点恢复、报告、组学模块、植入信号找回、命令行。"""

import json
import shutil

import openai
import pandas as pd
from conftest import DICTIONARY, continue_run, read_jsonl, start, write_config

from agentloop import cli
from agentloop.config import load_config, parse_config_text

try:  # openai 新版本基于 httpx2
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx


def _fingerprint(run_dir):
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    results = [{k: v for k, v in r.items()} for r in read_jsonl(run_dir / "results.jsonl")]
    hyps = sorted(p.name for p in (run_dir / "registry").glob("*.json"))
    rounds = [{k: v for k, v in r.items() if k != "tokens_total"} for r in state["rounds"]]
    return results, hyps, rounds, state["stop_reason"]


def test_resume_after_any_stage_matches_uninterrupted(tmp_path):
    full_dir, _, _ = start(tmp_path / "full", MAX_ROUNDS=2)
    expected = _fingerprint(full_dir)
    for k in (1, 3, 5, 6, 9):
        run_dir, config, state = start(tmp_path / f"cut{k}", stop_after=k, MAX_ROUNDS=2)
        assert state["status"] == "running"
        continue_run(run_dir, config)
        assert _fingerprint(run_dir) == expected, f"在第 {k} 个阶段后中断再恢复，结果不一致"


def test_report_has_progress_and_every_round(project):
    run_dir, _, state = start(project, MAX_ROUNDS=2)
    html = (run_dir / "研究报告.html").read_text(encoding="utf-8")
    assert "一、进展总览" in html and "data:image/png;base64" in html
    for r in state["rounds"]:
        assert f"第 {r['round']} 轮" in html
    assert "评测：植入信号找回情况" in html
    assert (run_dir / "研究报告.docx").stat().st_size > 10_000


def _dictionary_with_omics(path):
    sheets = pd.read_excel(DICTIONARY, sheet_name=None)
    extra = pd.DataFrame([{"一级模块": "14_基因与组学", "中文字段名": zh, "英文变量名": name, "数据类型": "numeric",
                           "证据等级": "C_探索扩展", "V1优先级": "P1"} for name, zh in
                          [("tear_il6_pg_ml", "泪液 IL-6"), ("tear_il17a_pg_ml", "泪液 IL-17A")]])
    sheets["字段字典"] = pd.concat([sheets["字段字典"], extra], ignore_index=True)
    with pd.ExcelWriter(path) as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    return path


def test_omics_module_off_by_default(project):
    run_dir, _, state = start(project, MAX_ROUNDS=1)
    assert state["omics"]["enabled"] is False
    findings = json.loads((run_dir / "rounds/r1/1_discovery.json").read_text(encoding="utf-8"))["findings"]
    assert all(f["source"] != "组学模块" for f in findings)


def test_omics_module_enabled_when_declared_and_present(project):
    dict_path = _dictionary_with_omics(project / "dict_omics.xlsx")
    run_dir, _, state = start(project, with_omics=True, MAX_ROUNDS=1, DATA_DICTIONARY=dict_path)
    assert state["omics"]["enabled"] and "tear_il6_pg_ml" in state["omics"]["fields"]
    findings = json.loads((run_dir / "rounds/r1/1_discovery.json").read_text(encoding="utf-8"))["findings"]
    assert any(f["source"] == "组学模块" and f["exposure"] == "tear_il6_pg_ml" for f in findings)


def test_strong_planted_signals_found_and_no_false_signals(project):
    run_dir, _, _ = start(project, n=8000, MAX_ROUNDS=3)
    ev = json.loads((run_dir / "evaluation/评测结果.json").read_text(encoding="utf-8"))
    status = {(r["exposure"], r["outcome"]): r["status"] for r in ev["rows"]}
    assert status[("sjogren_syndrome", "dry_eye_confirmed")] == "已找回"
    assert status[("mgd", "dry_eye_lipid_deficient")] == "已找回"
    assert ev["false_signals"] == []


def test_config_parsing_tolerates_bom_crlf_and_spaces(tmp_path):
    values = parse_config_text("\ufeff# 注释\r\nAPI_KEY = sk-abc \r\nMAX_ROUNDS=3\r\n")
    assert values["API_KEY"] == "sk-abc" and values["MAX_ROUNDS"] == "3"
    path = write_config(tmp_path)
    try:
        load_config(path, require_api_key=True)
        raise AssertionError("缺少 API Key 时应报错")
    except Exception as exc:
        assert "API Key" in str(exc)


def test_cli_run_and_resume_contract(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AGENTLOOP_NO_BROWSER", "1")
    cfg = write_config(tmp_path, MAX_ROUNDS=1)
    assert cli.main(["run", "--synthetic", "--synthetic-n", "3000", "--config", str(cfg), "--offline-llm", "--offline-sources"]) == 0
    out = capsys.readouterr().out
    assert "第 1 轮 · 正在数据发现" in out and "研究已完成" in out
    assert cli.main(["resume", "--config", str(cfg)]) == cli.EXIT_NOTHING_TO_RESUME
    assert "没有需要继续的研究" in capsys.readouterr().out


def test_cli_exit_code_when_budget_pauses(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLOOP_NO_BROWSER", "1")
    cfg = write_config(tmp_path, MAX_ROUNDS=1, TOKEN_BUDGET=3000)
    args = ["--config", str(cfg), "--offline-llm", "--offline-sources"]
    assert cli.main(["run", "--synthetic", "--synthetic-n", "3000", *args]) == cli.EXIT_PAUSED
    codes = [cli.main(["resume", *args]) for _ in range(6)]
    assert cli.EXIT_OK in codes


def test_cli_explains_bad_api_key_in_chinese():
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    exc = openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    assert "API_KEY" in cli._llm_error_message(exc)
    exc = openai.APIStatusError("no money", response=httpx.Response(402, request=req), body=None)
    assert "余额不足" in cli._llm_error_message(exc)


def test_real_data_directory_contract(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AGENTLOOP_NO_BROWSER", "1")
    data_dir = tmp_path / "数据"
    data_dir.mkdir()
    from agentloop import synthetic

    df, _ = synthetic.generate(n=3000)
    df.to_csv(data_dir / "patients.csv", index=False)
    cfg = write_config(tmp_path, MAX_ROUNDS=1)
    assert cli.main(["run", "--data", str(data_dir), "--config", str(cfg), "--offline-llm", "--offline-sources"]) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    assert not (run_dir / "evaluation" / "评测结果.json").exists()  # 真实数据不生成评测章节
    shutil.rmtree(data_dir)
    (tmp_path / "空数据").mkdir()
    assert cli.main(["run", "--data", str(tmp_path / "空数据"), "--config", str(cfg), "--offline-llm", "--offline-sources"]) == 1
    assert "patients.parquet" in capsys.readouterr().out
