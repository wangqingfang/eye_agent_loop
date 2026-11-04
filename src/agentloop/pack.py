"""打包分发：生成在 Windows 上解压不乱码的 zip。

Mac 访达「压缩」生成的 zip 用 UTF-8 存中文文件名，却不设置 zip 规范中的「文件名为 UTF-8」标记
（通用标志位第 11 位）。Windows 资源管理器见到没有标记的文件名，会按 GBK 解读，中文文件名就成了乱码，
而且这种乱码丢失了信息，无法还原。

本模块用 Python zipfile 打包：凡是含中文的文件名都会自动带上 UTF-8 标记，Windows 10/11、Mac、
7-Zip 等都能正确解压。打包内容是 git 跟踪的文件加上未被 .gitignore 忽略的新文件，不含 .venv、
.git、runs、数据、配置.txt（含 API Key）等。打包后逐项校验。
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import zipfile
from pathlib import Path

UTF8_FLAG = 0x800
TOP_DIR = "eye_agent_loop"
# 不在 git 管理下时使用的排除规则（与 .gitignore 一致）
EXCLUDE_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "runs", "数据", ".环境", "dist", ".idea", ".vscode"}
EXCLUDE_FILES = {"配置.txt", "环境检查报告.txt", ".DS_Store"}


def _git_files(proj: Path) -> list[str] | None:
    if not (proj / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(proj), "ls-files", "-z", "-co", "--exclude-standard"],
                             capture_output=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted(p for p in out.decode("utf-8").split("\0") if p and (proj / p).is_file())


def _walk_files(proj: Path) -> list[str]:
    files = []
    for root, dirs, names in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for n in names:
            if n not in EXCLUDE_FILES:
                files.append(Path(root, n).relative_to(proj).as_posix())
    return sorted(files)


def collect(proj: Path) -> list[str]:
    files = _git_files(proj)
    if files is None:
        files = _walk_files(proj)
    return [f for f in files if Path(f).name not in EXCLUDE_FILES and not set(Path(f).parts) & EXCLUDE_DIRS]


def build(proj: Path, out: Path | None = None) -> Path:
    proj = Path(proj).resolve()
    out = out or proj / "dist" / f"{TOP_DIR}_{_dt.date.today():%Y%m%d}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    files = collect(proj)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            info = zipfile.ZipInfo.from_file(proj / rel, f"{TOP_DIR}/{rel}")  # 保留 .command 的可执行权限
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (proj / rel).read_bytes())  # 原样写入字节：.bat 的 GBK + CRLF 不变
    return out


def verify(proj: Path, zip_path: Path) -> list[str]:
    """返回发现的问题；空列表表示通过。"""
    proj = Path(proj).resolve()
    problems = []
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        for info in infos:
            if any(ord(c) > 127 for c in info.filename) and not info.flag_bits & UTF8_FLAG:
                problems.append(f"文件名缺少 UTF-8 标记：{info.filename}")
            rel = info.filename.split("/", 1)[1]
            if z.read(info) != (proj / rel).read_bytes():
                problems.append(f"内容与原文件不一致：{rel}")
            if rel.endswith(".command") and not (info.external_attr >> 16) & 0o111:
                problems.append(f"缺少可执行权限：{rel}")
        names = {i.filename.split("/", 1)[1] for i in infos}
    for must in ["启动研究.command", "启动研究.bat", "安装环境.command", "安装环境.bat", "配置模板.txt",
                 "使用说明.md", "pyproject.toml", "uv.lock", "资料/干眼共病模型_数据字典_V1.0.xlsx"]:
        if must not in names:
            problems.append(f"缺少必需文件：{must}")
    for leaked in ["配置.txt"]:
        if leaked in names:
            problems.append(f"不应打包的文件：{leaked}")
    return problems


def run(proj: Path, out=print) -> int:
    proj = Path(proj).resolve()
    zip_path = build(proj)
    problems = verify(proj, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        n = len(z.infolist())
        n_cjk = sum(any(ord(c) > 127 for c in i.filename) for i in z.infolist())
    size_mb = zip_path.stat().st_size / 1024 ** 2
    if problems:
        out("打包完成，但校验发现问题：")
        for p in problems:
            out(f"  - {p}")
        return 1
    out(f"打包完成：{zip_path}")
    out(f"共 {n} 个文件、{size_mb:.1f} MB；其中 {n_cjk} 个中文文件名均已带 UTF-8 标记，Windows 解压不会乱码。")
    out("已排除：.venv、.git、runs、数据、配置.txt（含 API Key）、.环境 等。")
    out("把这个 zip 发给对方，对方解压后双击「启动研究」即可。请不要再用访达的「压缩」功能打包。")
    return 0
