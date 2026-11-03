# 14: 开箱即用：环境安装、环境检查与机器绑定

**What to build:** 没有编程经验的研究人员拿到文件夹后，只需双击启动文件：程序自动发现缺少运行环境、更换了电脑或移动了文件夹，经一次回车确认后自动安装（uv、Python、锁定版本的依赖），记录机器指纹，做完整环境检查和离线自检，然后进入菜单。每次启动做一次快速检查。提供可单独运行的安装与修复文件，以及预留的机器版本检查指令。

**Blocked by:** 13

**Status:** resolved

- [x] `安装环境.command` / `安装环境.bat`：检查本机 → 安装 uv → `uv sync --frozen --no-dev` → 写 `.环境/机器指纹.txt` → `agentloop doctor`；失败时给出中文原因并写 `.环境/安装日志.txt`
- [x] 启动文件在 uv 缺失、`.venv` 缺失、指纹缺失、`BIND`（系统-架构）不一致、`DIR` 不一致时提示并自动调用安装文件
- [x] 启动文件每次调用 `agentloop doctor --quick`，失败时提示双击「安装环境」修复
- [x] `agentloop doctor`：本机、Python、机器绑定、依赖、中文字体、数据字典、配置、磁盘、写入权限、外部来源网络、大模型 Key、离线自检；结果写入 `环境检查报告.txt`
- [x] `agentloop doctor --machine`：输出本机信息与机器绑定状态（JSON）
- [x] API Key 无效、PubMed 被拒只作为【警告】，不阻止安装
- [x] 强制使用 uv 管理的 Python（`UV_PYTHON_PREFERENCE=only-managed`），依赖版本由 `uv.lock` 锁定
- [x] Mac 上模拟全新电脑（空 HOME、PATH 中没有 uv、没有任何缓存）双击启动文件，从零安装到跑完一轮研究
- [x] Mac 上验证：第二次启动直接进菜单（约 3 秒）；移动文件夹后自动重建；伪造指纹模拟换电脑后自动重建
- [ ] 在 Windows 真机上走通安装与启动（含从 Mac 拷贝过来的文件夹）

## Comments

- 2026-11-03 Mac 实测：全新环境首次安装约 2.5 分钟（uv 0.13.7、Python 3.12.16、47 个依赖包）；移动文件夹后重建约 1 分钟（依赖来自本地缓存）。
- 调试中发现并修复：网络探测原来请求 `https://pypi.org/simple/`（约 48 MB 的索引页）导致超时，改为对 `simple/numpy/` 发 HEAD 请求；bash 在中文环境下会把紧跟变量名的中文字符当作变量名的一部分（`$VER（` 取不到值），已把所有紧邻中文的变量改为 `${VER}` 写法。
- Windows 两个 `.bat` 文件以 GBK + CRLF 保存，所有 `goto` / `call` 目标标签已核对存在，但未在 Windows 上运行过。
