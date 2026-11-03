"""命令行入口。启动契约见 13 号票：

  agentloop run --synthetic --config <配置.txt>
  agentloop run --data <数据目录> --config <配置.txt>
  agentloop resume --config <配置.txt>

退出码（启动文件据此给出不同提示）：
  0 研究已完成并打开报告；4 研究已暂停（如预算用完）并打开报告；3 没有需要继续的研究；
  1 使用者可以自行处理的问题（已打印中文说明，如 API Key 无效、余额不足、断网、数据格式不对）；
  2 程序缺陷或意外错误（需要技术同事处理，详情写入错误日志.txt）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import webbrowser
from pathlib import Path

from . import orchestrator
from .config import load_config
from .errors import ComplianceError, UserFacingError
from .offline_llm import OfflineRuleLLM
from .recorded_sources import RecordedSources
from .sources import Cache, OnlineSources

EXIT_OK, EXIT_USER_FIXABLE, EXIT_PROGRAM_ERROR, EXIT_NOTHING_TO_RESUME, EXIT_PAUSED = 0, 1, 2, 3, 4


def say(msg: str) -> None:
    print(msg, flush=True)


def _parser():
    p = argparse.ArgumentParser(prog="agentloop", description="干眼共病研究循环")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="开始新的研究循环")
    src = run.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true", help="使用依据数据字典生成的合成数据")
    src.add_argument("--data", type=Path, help="真实数据目录（含 patients.parquet 或 patients.csv）")
    run.add_argument("--synthetic-n", type=int, default=20_000, help="合成数据的患者数")
    run.add_argument("--with-omics", action="store_true", help="合成数据中加入组学字段（调试组学模块用）")
    res = sub.add_parser("resume", help="继续最近一次未完成的研究")
    rep = sub.add_parser("report", help="重新生成某次运行的 HTML 与 Word 报告")
    rep.add_argument("--run", type=Path, required=True)
    doc = sub.add_parser("doctor", help="环境检查（安装后与每次启动时使用）")
    doc.add_argument("--quick", action="store_true", help="快速检查：不联网、不跑离线自检")
    doc.add_argument("--machine", action="store_true", help="只输出本机信息与机器绑定状态")
    doc.add_argument("--config", type=Path, default=None)
    for sp in (run, res, rep):
        sp.add_argument("--config", type=Path, required=True)
        sp.add_argument("--no-browser", action="store_true")
    for sp in (run, res):
        sp.add_argument("--offline-llm", action="store_true", help="用离线规则引擎代替大模型（仅调试）")
        sp.add_argument("--offline-sources", action="store_true", help="用离线模拟来源代替联网检索（仅调试）")
    return p


def _backend(config, llm_mode):
    if llm_mode == "offline":
        return OfflineRuleLLM()
    from .llm import OpenAICompatBackend

    return OpenAICompatBackend(config.api_key, config.base_url, config.model)


def _sources(run_dir: Path, config, sources_mode):
    if sources_mode == "offline":
        return RecordedSources()
    return OnlineSources(Cache(run_dir / "cache"), ncbi_api_key=config.ncbi_api_key)


def _open(path: Path, args) -> None:
    if args.no_browser or os.environ.get("AGENTLOOP_NO_BROWSER"):
        return
    try:
        webbrowser.open(path.resolve().as_uri())
    except Exception:
        pass


def _llm_error_message(exc) -> str | None:
    try:
        import openai
    except ImportError:
        return None
    if isinstance(exc, openai.AuthenticationError):
        return "大模型拒绝了 API Key：Key 可能填错或已失效。请检查「配置.txt」中的 API_KEY，改好后选择「继续上次的研究」。"
    if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
        return "大模型账户余额不足。请到大模型平台充值后，选择「继续上次的研究」。"
    if isinstance(exc, openai.RateLimitError):
        return "大模型请求太频繁或额度受限。请稍等几分钟后选择「继续上次的研究」。"
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return "连接大模型失败，可能是网络断开。请检查网络后选择「继续上次的研究」，已完成的部分不会重复。"
    if isinstance(exc, openai.APIStatusError):
        return f"大模型服务返回错误（HTTP {exc.status_code}）。请稍后选择「继续上次的研究」；若反复出现，请联系技术同事。"
    return None


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    run_dir = None
    if args.command == "doctor":
        from .doctor import run_doctor

        return run_doctor(quick=args.quick, machine_only=args.machine, config_path=args.config, out=say)
    try:
        if args.command == "report":
            config = load_config(args.config, require_api_key=False)
            path = orchestrator.render(args.run, config)
            say(f"报告已重新生成：{path}")
            _open(path, args)
            return 0
        # 调试开关（技术同事用）：环境变量 AGENTLOOP_OFFLINE_LLM / AGENTLOOP_OFFLINE_SOURCES 等同于对应参数
        offline_llm = args.offline_llm or bool(os.environ.get("AGENTLOOP_OFFLINE_LLM"))
        offline_sources = args.offline_sources or bool(os.environ.get("AGENTLOOP_OFFLINE_SOURCES"))
        llm_mode = "offline" if offline_llm else "online"
        sources_mode = "offline" if offline_sources else "online"
        if args.command == "resume":
            config = load_config(args.config, require_api_key=False)
            run_dir = orchestrator.latest_unfinished(config.project_dir)
            if run_dir is None:
                say("没有需要继续的研究：最近的研究都已完成。如需开始新的研究，请选择 1 或 2。")
                return EXIT_NOTHING_TO_RESUME
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            llm_mode, sources_mode = state["llm_mode"], state["sources_mode"]
            config = load_config(args.config, require_api_key=llm_mode == "online")
            say(f"继续第 {state['round']} 轮的研究（运行编号 {state['run_id']}）。")
        else:
            config = load_config(args.config, require_api_key=llm_mode == "online")
            if args.synthetic:
                say(f"正在生成合成数据（{args.synthetic_n:,} 名虚拟患者）……")
            run_dir = orchestrator.new_run(config.project_dir, config, None if args.synthetic else args.data,
                                           synthetic_n=args.synthetic_n, with_omics=args.with_omics,
                                           llm_mode=llm_mode, sources_mode=sources_mode)
            say(f"研究已开始，运行编号 {run_dir.name}。")
        backend = _backend(config, llm_mode)
        state = orchestrator.run(run_dir, config, backend, _sources(run_dir, config, sources_mode), progress=say)
        report = run_dir / "研究报告.html"
        if state["status"] == "completed":
            say(f"研究已完成：{state['stop_reason']}。")
        else:
            say(f"研究已暂停：{state['stop_reason']}")
        say(f"报告：{report}")
        _open(report, args)
        return EXIT_OK if state["status"] == "completed" else EXIT_PAUSED
    except UserFacingError as exc:
        say(str(exc))
        return EXIT_USER_FIXABLE
    except KeyboardInterrupt:
        say("已中断。已完成的阶段都已保存，下次选择「继续上次的研究」即可接着跑。")
        return EXIT_USER_FIXABLE
    except ComplianceError as exc:
        _log(run_dir, exc)
        say(f"出于隐私保护，程序已停止：{exc}。这是程序缺陷，请把 runs 里最新文件夹中的「错误日志.txt」发给技术同事。")
        return EXIT_PROGRAM_ERROR
    except Exception as exc:  # noqa: BLE001
        msg = _llm_error_message(exc)
        _log(run_dir, exc)
        if msg:
            say(msg)
            return EXIT_USER_FIXABLE
        say("程序出现意外错误，详情已写入 runs 文件夹中最新运行的「错误日志.txt」。")
        return EXIT_PROGRAM_ERROR


def _log(run_dir, exc) -> None:
    target = (run_dir or Path.cwd() / "runs") / "错误日志.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write("".join(traceback.format_exception(exc)) + "\n")


if __name__ == "__main__":
    sys.exit(main())
