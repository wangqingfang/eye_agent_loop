# 干眼共病研究 AgentLoop

## 开发

- 运行测试：`uv run pytest`（离线规则引擎 + 离线来源，不联网、不花钱）。
- 调试整条链路：`uv run agentloop run --synthetic --config 配置.txt --offline-llm --offline-sources`。
- 最终使用者没有编程经验：所有面向使用者的输出必须是中文、可操作的；改动行为后同步更新 `使用说明.md`。
- `启动研究.bat`、`安装环境.bat` 以 GBK + CRLF 保存，修改时先转成 UTF-8，改完再转回。
- `.command` 脚本里紧挨中文的变量必须写成 `${VAR}`，否则 bash 在中文环境下会把中文当成变量名的一部分。
- 环境检查：`uv run agentloop doctor`（`--quick` 快速、`--machine` 机器信息）；安装与机器绑定见 14 号票。
- 在本目录双击启动文件会以 `--no-dev` 同步环境、移除 pytest；之后 `uv run pytest` 会自动装回。
- 分发给别人只用 `打包分发.command`（`agentloop pack`）或 GitHub 的 Download ZIP；访达「压缩」不写 UTF-8 文件名标记，Windows 解压会乱码。
- 启动契约（命令、参数、退出码）见 `.scratch/research-loop/issues/13-non-programmer-launcher-and-guide.md`。

## Agent skills

### Issue tracker

Issue 和 spec 以本地 markdown 文件形式存放在 `.scratch/<feature>/` 下。See `docs/agents/issue-tracker.md`.

### Triage labels

使用默认的五个 triage 角色标签（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`），记录在 issue 文件顶部的 `Status:` 行。See `docs/agents/triage-labels.md`.

### Domain docs

单上下文布局：本目录下的 `GLOSSARY.md` 与 `docs/adr/`。See `docs/agents/domain.md`.
