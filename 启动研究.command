#!/bin/bash
# 干眼共病研究助手 · Mac 启动文件
# 双击运行。只负责：检查并在需要时安装运行环境 → 检查配置 → 显示菜单 → 调用主程序。
# 所有研究逻辑都在主程序（agentloop 命令）里，本文件不包含。

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

CONFIG="$DIR/配置.txt"
TEMPLATE="$DIR/配置模板.txt"
DATA_DIR="$DIR/数据"
RUNS_DIR="$DIR/runs"

pause_and_exit() {
  echo
  read -r -p "按回车键关闭窗口……" _
  exit "${1:-0}"
}

echo
echo "=========================================="
echo "          干眼共病研究助手"
echo "=========================================="
echo

# ---- 1. 检查运行环境：没有安装、换了电脑或移动了文件夹时自动安装 ----
find_uv() {
  UV="$(command -v uv 2>/dev/null)"
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
    [ -n "$UV" ] && break
    [ -x "$candidate" ] && UV="$candidate"
  done
}
find_uv
FP="$DIR/.环境/机器指纹.txt"
BIND="$(uname -s)-$(uname -m)"
REASON=""
if [ -z "$UV" ]; then
  REASON="这台电脑还没有安装运行环境。"
elif [ ! -x "$DIR/.venv/bin/python" ] || [ ! -f "$FP" ]; then
  REASON="运行环境还没有安装完成。"
elif [ "$(sed -n 's/^BIND=//p' "$FP")" != "$BIND" ]; then
  REASON="检测到这是另一台电脑（运行环境与本机不匹配）。"
elif [ "$(sed -n 's/^DIR=//p' "$FP")" != "$DIR" ]; then
  REASON="检测到文件夹被移动过，需要重建运行环境。"
fi
if [ -n "$REASON" ]; then
  echo "$REASON"
  echo "需要联网自动安装（第一次约下载 500 MB，通常几分钟）。"
  read -r -p "按回车键开始安装（输入 N 再按回车则退出）：" ans
  case "$ans" in
    n|N) exit 0 ;;
  esac
  bash "$DIR/安装环境.command" --from-launcher || pause_and_exit 1
  find_uv
  echo
  echo "=========================================="
  echo
fi
export UV_PYTHON_PREFERENCE=only-managed
if ! QUICK="$("$UV" run --frozen --no-dev --project "$DIR" agentloop doctor --quick 2>&1)"; then
  echo "$QUICK"
  echo
  echo "运行环境有问题。请双击「安装环境.command」修复，修复后再双击启动。"
  pause_and_exit 1
fi

# ---- 2. 检查配置文件 ----
has_api_key() {
  grep -Eq '^[[:space:]]*API_KEY[[:space:]]*=[[:space:]]*[^[:space:]]+' "$CONFIG"
}

if [ ! -f "$CONFIG" ]; then
  if [ ! -f "$TEMPLATE" ]; then
    echo "找不到「配置模板.txt」，文件夹可能不完整。请联系技术同事。"
    pause_and_exit 1
  fi
  cp "$TEMPLATE" "$CONFIG"
  echo "这是第一次使用，已为你创建配置文件「配置.txt」。"
  echo "马上会用「文本编辑」打开它：请把 API Key 粘贴到 API_KEY= 后面，然后保存（⌘S）。"
  echo
  read -r -p "准备好了就按回车键……" _
  open -e "$CONFIG"
  echo
  read -r -p "填好并保存后，回到这个窗口按回车键继续……" _
fi

if ! has_api_key; then
  echo "配置文件里还没有填写 API Key。"
  echo "请打开本文件夹里的「配置.txt」，把 API Key 粘贴到 API_KEY= 后面，保存后重新双击启动。"
  open -e "$CONFIG"
  pause_and_exit 1
fi

# ---- 3. 菜单 ----
folder_has_files() {
  [ -d "$1" ] && [ -n "$(ls -A "$1" 2>/dev/null)" ]
}

while true; do
  echo "请选择要做什么："
  echo
  echo "  1  使用模拟数据（第一次建议选这个）"
  echo "  2  使用真实数据（数据需已放入「数据」文件夹）"
  echo "  3  继续上次的研究"
  echo "  0  退出"
  echo
  read -r -p "请输入数字后按回车键：" choice
  echo
  case "$choice" in
    1) ARGS=(run --synthetic); break ;;
    2)
      if ! folder_has_files "$DATA_DIR"; then
        echo "「数据」文件夹不存在或是空的。请先请技术同事把转换好的数据放进去。"
        echo
        continue
      fi
      ARGS=(run --data "$DATA_DIR"); break ;;
    3)
      if ! folder_has_files "$RUNS_DIR"; then
        echo "还没有做过任何研究，无法继续。请先选择 1 或 2。"
        echo
        continue
      fi
      ARGS=(resume); break ;;
    0) exit 0 ;;
    *) echo "没有这个选项，请输入 0、1、2 或 3。"; echo ;;
  esac
done

# ---- 4. 调用主程序 ----
echo "正在启动，请不要关闭窗口……"
echo
"$UV" run --frozen --no-dev --project "$DIR" agentloop "${ARGS[@]}" --config "$CONFIG"
rc=$?
echo
case "$rc" in
  0) echo "已完成。报告已在浏览器中打开，也可以在 runs 文件夹里找到。" ;;
  4) echo "研究已暂停，目前的报告已在浏览器中打开。之后重新双击启动、输入 3 即可接着跑。" ;;
  3) ;;
  1) echo "请按上面的提示处理，然后重新双击启动、输入 3 继续，已完成的部分不会重复。" ;;
  *)
    echo "运行没有成功。"
    echo "请把这个窗口截图，连同 runs 文件夹里最新的那个文件夹，一起发给技术同事。"
    echo "注意：不要发送「数据」文件夹。" ;;
esac
pause_and_exit "$rc"
