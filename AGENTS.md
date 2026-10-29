# 给 Codex 的说明

本项目的规则与 `CLAUDE.md` **完全相同**，请先完整阅读 `CLAUDE.md` 并照做。进度在 `docs/progress.md`，规格在 `docs/spec.md`。
（Claude Code 的 `reviewer` 子代理在 Codex 中不可用，审查步骤可以跳过，或者由用户之后用 Claude Code 补做。）
- 仓库内容（文件内容、路径、提交信息）不得出现本机真实用户名或机器名，用 `<user>` 之类的占位代替；提交前运行 `.venv\Scripts\python tools/check_private.py`（默认检查暂存区，命中就先改掉再提交）。
