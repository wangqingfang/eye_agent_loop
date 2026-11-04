#!/bin/bash
# 干眼共病研究助手 · 打包分发（Mac）
# 双击运行，在 dist 文件夹里生成一个 zip，发给别人（尤其是 Windows 电脑）解压不会出现中文乱码。
# 不要用访达的「压缩」功能打包：它生成的 zip 在 Windows 上解压，中文文件名会变成乱码。

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

pause_and_exit() {
  echo
  read -r -p "按回车键关闭窗口……" _
  exit "${1:-0}"
}

echo
echo "=========================================="
echo "      干眼共病研究助手 · 打包分发"
echo "=========================================="
echo

UV="$(command -v uv 2>/dev/null)"
for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
  [ -n "$UV" ] && break
  [ -x "$c" ] && UV="$c"
done

if [ -n "$UV" ] && [ -x "$DIR/.venv/bin/python" ]; then
  "$DIR/.venv/bin/python" -c "import sys; sys.path.insert(0, 'src'); from agentloop import pack; sys.exit(pack.run(__import__('pathlib').Path('.')))"
  rc=$?
elif command -v git >/dev/null 2>&1 && [ -d "$DIR/.git" ]; then
  # 没有安装运行环境时的备用方案：git archive 生成的 zip 同样带 UTF-8 文件名标记
  mkdir -p "$DIR/dist"
  OUT="$DIR/dist/eye_agent_loop_$(date +%Y%m%d).zip"
  git -C "$DIR" archive --format=zip --prefix=eye_agent_loop/ -o "$OUT" HEAD
  rc=$?
  [ "$rc" = 0 ] && echo "打包完成：${OUT}（只包含已提交到 git 的内容）"
else
  echo "这台电脑还没有安装运行环境。请先双击「安装环境.command」，再双击本文件。"
  rc=1
fi
[ "$rc" = 0 ] && open "$DIR/dist" 2>/dev/null
pause_and_exit "$rc"
