import json
from pathlib import Path

import pytest

from agentloop import orchestrator
from agentloop.config import load_config
from agentloop.offline_llm import OfflineRuleLLM
from agentloop.recorded_sources import RecordedSources

PROJECT = Path(__file__).resolve().parents[1]
DICTIONARY = PROJECT / "资料" / "干眼共病模型_数据字典_V1.0.xlsx"


class RecordingBackend:
    """包住离线规则引擎，记录每次发给 LLM 的消息；可按阶段改写回复（模拟大模型犯错）。"""

    name = "recording"

    def __init__(self, inner=None, rewrite=None):
        self.inner = inner or OfflineRuleLLM()
        self.rewrite = rewrite or {}
        self.calls = []

    def chat(self, stage, messages, tools=None, json_mode=False):
        self.calls.append({"stage": stage, "messages": json.loads(json.dumps(messages, default=str))})
        resp = self.inner.chat(stage, messages, tools=tools, json_mode=json_mode)
        if stage in self.rewrite and not resp.tool_calls:
            resp.content = json.dumps(self.rewrite[stage](json.loads(resp.content)), ensure_ascii=False)
        return resp


def write_config(project_dir: Path, **values) -> Path:
    base = {"API_KEY": "", "MAX_ROUNDS": "2", "TOKEN_BUDGET": "2000000", "DATA_DICTIONARY": str(DICTIONARY)}
    base.update({k: str(v) for k, v in values.items()})
    path = project_dir / "配置.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{k}={v}" for k, v in base.items()) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path):
    return tmp_path


def start(project_dir, n=4000, backend=None, stop_after=None, with_omics=False, salt="fixed-salt", **cfg):
    config = load_config(write_config(project_dir, **cfg), require_api_key=False)
    run_dir = orchestrator.new_run(project_dir, config, None, synthetic_n=n, with_omics=with_omics,
                                   llm_mode="offline", sources_mode="offline", split_salt=salt)
    return run_dir, config, continue_run(run_dir, config, backend, stop_after)


def continue_run(run_dir, config, backend=None, stop_after=None):
    try:
        return orchestrator.run(run_dir, config, backend or OfflineRuleLLM(), RecordedSources(),
                                progress=lambda m: None, stop_after_stages=stop_after)
    except orchestrator.Interrupted:
        return json.loads((run_dir / "state.json").read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
