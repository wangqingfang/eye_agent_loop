"""环境检查（agentloop doctor）。

  agentloop doctor            完整检查：本机、依赖、字体、数据字典、配置、磁盘、网络、大模型 Key、离线自检
  agentloop doctor --quick    快速检查：不联网、不跑自检（每次启动时使用）
  agentloop doctor --machine  只输出本机信息与机器绑定状态（预留的机器版本检查指令）

结果用中文逐项打印，并写入项目目录下的「环境检查报告.txt」。存在【失败】项时退出码为 1。
"""

from __future__ import annotations

import datetime as _dt
import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PASS, WARN, FAIL = "通过", "警告", "失败"
PACKAGES = ["numpy", "pandas", "pyarrow", "openpyxl", "scipy", "statsmodels", "matplotlib", "docx", "openai", "requests"]
CJK_FONTS = ["Arial Unicode MS", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "SimHei", "Noto Sans CJK SC"]
MIN_FREE_GB = 2.0
FINGERPRINT = Path(".环境") / "机器指纹.txt"
NETWORK = [
    ("Europe PMC（文献）", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=dry%20eye&format=json&pageSize=1"),
    ("ClinicalTrials.gov（临床试验）", "https://clinicaltrials.gov/api/v2/studies?pageSize=1&fields=NCTId"),
    ("Open Targets（靶点）", "https://api.platform.opentargets.org/api/v4/graphql"),
    ("PubMed（文献，可选）", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?retmode=json"),
]


def project_dir() -> Path:
    """项目目录：包含 pyproject.toml 的 AgentLoop 文件夹。"""
    here = Path(__file__).resolve()
    for p in [Path.cwd(), *here.parents]:
        if (p / "pyproject.toml").exists() and (p / "src" / "agentloop").exists():
            return p
    return Path.cwd()


def _uv_version() -> str:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"))
    try:
        return subprocess.run([uv, "--version"], capture_output=True, text=True, timeout=10).stdout.strip() or "未知"
    except Exception:
        return "未找到"


def _memory_gb():
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except (ValueError, AttributeError, OSError):
        return None


def machine_info(proj: Path) -> dict:
    system = platform.system()
    if system == "Darwin":
        os_name, os_ver = "macOS", platform.mac_ver()[0]
    elif system == "Windows":
        os_name, os_ver = "Windows", platform.version()
    else:
        os_name, os_ver = system, platform.release()
    return {
        "操作系统": os_name, "系统版本": os_ver, "处理器架构": platform.machine(),
        "绑定标识": f"{system}-{platform.machine()}", "项目目录": str(proj),
        "Python": platform.python_version(), "Python 路径": sys.executable, "uv": _uv_version(),
        "CPU 核数": os.cpu_count(), "内存（GB）": _memory_gb(),
        "可用磁盘（GB）": round(shutil.disk_usage(proj).free / 1024 ** 3, 1),
    }


def read_fingerprint(proj: Path) -> dict:
    path = proj / FINGERPRINT
    if not path.exists():
        return {}
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:  # Windows 安装脚本按 GBK 写入
        text = raw.decode("gbk", errors="replace")
    values = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def binding_status(proj: Path, info: dict) -> tuple[str, str]:
    fp = read_fingerprint(proj)
    if not fp:
        return WARN, "没有找到安装记录（.环境/机器指纹.txt）。请双击「安装环境」完成一次安装。"
    bind, saved_dir = fp.get("BIND", ""), fp.get("DIR", "")
    same_dir = Path(saved_dir.rstrip("\\/")).resolve() == proj.resolve() if saved_dir else False
    if bind != info["绑定标识"]:
        return FAIL, f"运行环境是在另一台机器上安装的（{bind}），当前机器是 {info['绑定标识']}。请重新双击「安装环境」。"
    if not same_dir:
        return WARN, f"文件夹被移动过（安装时在 {saved_dir}）。启动时会自动重建运行环境。"
    return PASS, f"运行环境与本机匹配（{bind}，安装于 {fp.get('INSTALLED', '未知时间')}）"


# ---------------- 各项检查：每项返回 (名称, 结果, 说明) ----------------
def check_python():
    ok = sys.version_info >= (3, 11)
    return "Python 版本", PASS if ok else FAIL, platform.python_version() + ("" if ok else "（需要 3.11 及以上，请重新安装环境）")


def check_os(info):
    if info["操作系统"] == "macOS":
        major = int((info["系统版本"] or "0").split(".")[0] or 0)
        return "操作系统", PASS if major >= 11 else WARN, f"macOS {info['系统版本']}（{info['处理器架构']}）" + ("" if major >= 11 else "，建议 macOS 11 及以上")
    if info["操作系统"] == "Windows":
        return "操作系统", PASS, f"Windows {info['系统版本']}（{info['处理器架构']}）"
    return "操作系统", WARN, f"{info['操作系统']} {info['系统版本']}：未专门测试过的系统"


def check_packages():
    missing, versions = [], []
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
            versions.append(f"{name} {getattr(mod, '__version__', '')}".strip())
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{name}（{type(exc).__name__}）")
    if missing:
        return "依赖包", FAIL, "无法加载：" + "、".join(missing) + "。请重新双击「安装环境」。"
    return "依赖包", PASS, f"{len(versions)} 个依赖全部可用"


def check_fonts():
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    found = [f for f in CJK_FONTS if f in names]
    if found:
        return "图表中文字体", PASS, "、".join(found[:2])
    return "图表中文字体", WARN, "没有找到中文字体，报告图表里的中文可能显示为方框（表格和文字不受影响）"


def check_dictionary(config_path):
    from .config import DEFAULT_DICTIONARY, load_config
    from .dictionary import DataDictionary

    try:
        path = load_config(config_path, require_api_key=False).data_dictionary if config_path.exists() else project_dir() / DEFAULT_DICTIONARY
        d = DataDictionary.load(path)
        return "数据字典", PASS, f"{path.name}，{len(d.fields)} 个字段"
    except Exception as exc:  # noqa: BLE001
        return "数据字典", FAIL, str(exc)


def check_config(config_path):
    from .config import load_config

    if not config_path.exists():
        return "配置文件", WARN, "还没有「配置.txt」。第一次双击「启动研究」时会自动创建。"
    try:
        cfg = load_config(config_path, require_api_key=False)
    except Exception as exc:  # noqa: BLE001
        return "配置文件", FAIL, str(exc)
    if not cfg.api_key:
        return "配置文件", WARN, "API_KEY 还没有填写，开始研究前需要填写"
    return "配置文件", PASS, f"模型 {cfg.model}，最多 {cfg.max_rounds} 轮，每次启动 token 上限 {cfg.token_budget:,}"


def check_disk(info):
    free = info["可用磁盘（GB）"]
    return "磁盘空间", PASS if free >= MIN_FREE_GB else WARN, f"剩余 {free} GB" + ("" if free >= MIN_FREE_GB else f"，建议至少 {MIN_FREE_GB} GB")


def check_writable(proj):
    try:
        (proj / "runs").mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=proj / "runs"):
            pass
        return "写入权限", PASS, "runs 文件夹可写"
    except OSError as exc:
        return "写入权限", FAIL, f"无法在 runs 文件夹写入文件：{exc}。请把整个文件夹放到桌面或「文稿」里再试。"


def check_network():
    import requests

    rows = []
    for name, url in NETWORK:
        try:
            if "graphql" in url:
                r = requests.post(url, json={"query": "{meta{name}}"}, timeout=8)
            else:
                r = requests.get(url, timeout=8, allow_redirects=False)
            ok = r.status_code == 200
            note = "可以连接" if ok else f"返回 HTTP {r.status_code}"
            if not ok and "PubMed" in name:
                note += "（被拒绝不影响使用，程序会改用 Europe PMC 检索同一批文献）"
            rows.append((f"网络：{name}", PASS if ok else WARN, note))
        except Exception as exc:  # noqa: BLE001
            rows.append((f"网络：{name}", WARN, f"无法连接（{type(exc).__name__}），研究时这部分检索会被跳过"))
    return rows


def check_llm(config_path):
    from .config import load_config

    if not config_path.exists():
        return "大模型 API Key", WARN, "还没有配置文件，跳过"
    cfg = load_config(config_path, require_api_key=False)
    if not cfg.api_key:
        return "大模型 API Key", WARN, "未填写，跳过"
    try:
        from openai import OpenAI

        OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=15, max_retries=0).models.list()
        return "大模型 API Key", PASS, f"{cfg.base_url} 接受了这个 Key"
    except Exception as exc:  # noqa: BLE001
        # API Key 属于使用者配置而不是运行环境，这里只提醒，不让环境检查失败
        import openai

        if isinstance(exc, openai.AuthenticationError):
            return "大模型 API Key", WARN, "大模型拒绝了这个 Key（填错或已失效）。请检查「配置.txt」中的 API_KEY，开始研究前改好即可"
        if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
            return "大模型 API Key", WARN, "Key 有效，但账户余额不足，开始研究前请先充值"
        return "大模型 API Key", WARN, f"暂时无法验证（{type(exc).__name__}），可能是网络问题"


def check_selftest():
    """离线跑一个最小的研究循环（不联网、不花钱），检验统计、报告、Word 导出整条链路。"""
    from . import orchestrator
    from .config import load_config
    from .offline_llm import OfflineRuleLLM
    from .recorded_sources import RecordedSources

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg_path = tmp / "配置.txt"
        cfg_path.write_text(f"MAX_ROUNDS=1\nDATA_DICTIONARY={project_dir() / '资料' / '干眼共病模型_数据字典_V1.0.xlsx'}\n", encoding="utf-8")
        try:
            cfg = load_config(cfg_path, require_api_key=False)
            run_dir = orchestrator.new_run(tmp, cfg, None, synthetic_n=2000, llm_mode="offline", sources_mode="offline")
            state = orchestrator.run(run_dir, cfg, OfflineRuleLLM(), RecordedSources(), progress=lambda m: None)
            ok = state["status"] == "completed" and (run_dir / "研究报告.html").exists() and (run_dir / "研究报告.docx").exists()
            return "离线自检", PASS if ok else FAIL, "合成数据 → 五个阶段 → HTML 与 Word 报告，全部正常" if ok else f"自检未完成：{state['status']}"
        except Exception as exc:  # noqa: BLE001
            return "离线自检", FAIL, f"{type(exc).__name__}: {exc}"[:300]


def run_doctor(quick=False, machine_only=False, config_path=None, out=print) -> int:
    proj = project_dir()
    config_path = Path(config_path) if config_path else proj / "配置.txt"
    info = machine_info(proj)
    bind = binding_status(proj, info)
    if machine_only:
        out(json.dumps({**info, "机器绑定": {"结果": bind[0], "说明": bind[1]}, "安装记录": read_fingerprint(proj)},
                       ensure_ascii=False, indent=2))
        return 0 if bind[0] != FAIL else 1
    rows = [check_os(info), check_python(), ("机器绑定", *bind), check_packages(), check_fonts(),
            check_dictionary(config_path), check_config(config_path), check_disk(info), check_writable(proj)]
    if not quick:
        rows += check_network()
        rows.append(check_llm(config_path))
        rows.append(check_selftest())
    lines = [f"干眼共病研究助手 · 环境检查（{'快速' if quick else '完整'}）  {_dt.datetime.now():%Y-%m-%d %H:%M}", ""]
    lines += [f"【{r}】{name}：{note}" for name, r, note in rows]
    n_fail, n_warn = sum(r == FAIL for _, r, _ in rows), sum(r == WARN for _, r, _ in rows)
    lines += ["", "结论：" + ("环境可以正常使用。" if n_fail == 0 else f"有 {n_fail} 项失败，请按说明处理后重新检查。")
              + (f"（另有 {n_warn} 项提醒，不影响使用）" if n_warn and n_fail == 0 else "")]
    for line in lines:
        out(line)
    if not quick:
        (proj / "环境检查报告.txt").write_text("\n".join(lines) + "\n\n本机信息：\n" + json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if n_fail else 0
