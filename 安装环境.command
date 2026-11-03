#!/bin/bash
# 干眼共病研究助手 · Mac 环境安装与检查
# 双击运行，或由「启动研究」在需要时自动调用。可以重复运行，用来修复环境。
# 步骤：1 检查本机 → 2 安装 uv → 3 安装 Python 与依赖 → 4 记录机器指纹 → 5 环境检查与离线自检

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
ENV_DIR="$DIR/.环境"
LOG="$ENV_DIR/安装日志.txt"
FP="$ENV_DIR/机器指纹.txt"
FROM_LAUNCHER=0
[ "$1" = "--from-launcher" ] && FROM_LAUNCHER=1
mkdir -p "$ENV_DIR"
echo "==== $(date '+%Y-%m-%d %H:%M:%S') 开始安装 ====" >> "$LOG"

finish() {
  if [ "$FROM_LAUNCHER" = 0 ]; then
    echo
    read -r -p "按回车键关闭窗口……" _
  fi
  exit "$1"
}

fail() {
  echo
  echo "安装没有完成：$1"
  echo "详细记录在本文件夹的「.环境/安装日志.txt」。处理后可以再次双击「安装环境.command」重试；"
  echo "如果仍然不行，请把这个窗口截图，连同这个日志文件，一起发给技术同事。"
  echo "安装失败：$1" >> "$LOG"
  finish 1
}

step() {
  echo
  echo "[$1/5] $2"
}

echo
echo "=========================================="
echo "     干眼共病研究助手 · 安装运行环境"
echo "=========================================="
echo "需要联网。第一次安装约下载 500 MB，通常几分钟，请不要关闭窗口。"

# ---- 1. 检查本机 ----
step 1 "检查本机"
[ "$(uname -s)" = "Darwin" ] || fail "这个安装文件只适用于 Mac。Windows 电脑请双击「安装环境.bat」。"
ARCH="$(uname -m)"
VER="$(sw_vers -productVersion 2>/dev/null)"
MAJOR="${VER%%.*}"
FREE_GB="$(df -g "$DIR" | awk 'NR==2 {print $4}')"
echo "  macOS ${VER}（${ARCH}），磁盘剩余 ${FREE_GB} GB"
[ "${MAJOR:-0}" -ge 11 ] 2>/dev/null || echo "  提醒：macOS $VER 比较旧，建议升级到 11 或以上；仍会尝试安装。"
[ "${FREE_GB:-0}" -ge 2 ] 2>/dev/null || fail "磁盘剩余空间不足 2 GB（现在 ${FREE_GB} GB）。请清理磁盘后重试。"
if ! curl -sSfI -m 15 -o /dev/null https://pypi.org/simple/numpy/ 2>>"$LOG"; then
  fail "无法连接网络（pypi.org）。安装需要联网，请检查网络或代理后重试。"
fi
echo "  网络正常"

# ---- 2. 安装 uv ----
step 2 "安装 uv（Python 运行环境管理工具）"
find_uv() {
  UV="$(command -v uv 2>/dev/null)"
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
    [ -n "$UV" ] && break
    [ -x "$c" ] && UV="$c"
  done
}
find_uv
if [ -z "$UV" ]; then
  echo "  正在下载 uv……"
  curl -LsSf https://astral.sh/uv/install.sh | sh >> "$LOG" 2>&1 || fail "下载 uv 失败（多为网络问题）。"
  find_uv
  [ -n "$UV" ] || fail "uv 安装后仍找不到。"
fi
UV_VER="$("$UV" --version 2>>"$LOG")" || fail "uv 无法运行。"
echo "  $UV_VER"

# ---- 3. 安装 Python 与依赖 ----
step 3 "安装 Python 与依赖（按 uv.lock 锁定的版本）"
BIND="$(uname -s)-$ARCH"
if [ -f "$FP" ]; then
  OLD_BIND="$(sed -n 's/^BIND=//p' "$FP")"
  OLD_DIR="$(sed -n 's/^DIR=//p' "$FP")"
  if [ "$OLD_BIND" != "$BIND" ] || [ "$OLD_DIR" != "$DIR" ]; then
    echo "  检测到更换了电脑或移动了文件夹，正在重建运行环境……"
    rm -rf "$DIR/.venv"
  fi
fi
export UV_PYTHON_PREFERENCE=only-managed
if ! "$UV" sync --frozen --no-dev --project "$DIR" >> "$LOG" 2>&1; then
  echo "  第一次尝试失败，清理后重试一次……"
  rm -rf "$DIR/.venv"
  "$UV" sync --frozen --no-dev --project "$DIR" >> "$LOG" 2>&1 || fail "下载或安装依赖失败（多为网络问题）。"
fi
PY_VER="$("$DIR/.venv/bin/python" -V 2>&1)" || fail "Python 安装后无法运行。"
echo "  $PY_VER 与依赖已安装"

# ---- 4. 记录机器指纹 ----
step 4 "记录机器指纹（运行环境与本机绑定）"
{
  echo "BIND=$BIND"
  echo "DIR=$DIR"
  echo "OS=macOS $VER"
  echo "UV=$UV_VER"
  echo "PYTHON=$PY_VER"
  echo "INSTALLED=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$FP"
echo "  ${BIND}，$DIR"

# ---- 5. 环境检查与离线自检 ----
step 5 "环境检查与离线自检"
echo
"$UV" run --frozen --no-dev --project "$DIR" agentloop doctor
DOCTOR_RC=$?
echo "==== 环境检查退出码 $DOCTOR_RC ====" >> "$LOG"
[ "$DOCTOR_RC" = 0 ] || fail "环境检查有失败项，请按上面【失败】一行的说明处理。"

echo
echo "安装完成，可以开始使用了。以后双击「启动研究.command」即可。"
echo "检查结果已保存到「环境检查报告.txt」。"
finish 0
