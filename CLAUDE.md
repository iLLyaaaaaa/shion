# Shion（诗音）—— Claude 的桌宠

用 Python + PySide6 做的 Windows 桌宠，可以通过 hooks 和 Claude Code 联动（显示工作状态、同意/否决、暂停/继续、反馈）。非官方粉丝作品。

## 每次会话开始时
1. 先读 `docs/progress.md`，弄清楚做到哪一步、下一步做什么
2. 只读 `docs/spec.md` 中**和当前这一步有关的章节**，不要通读全文
3. 一个会话只做 progress.md 里的**一个步骤**

## 规矩
- 用户是计算机专业大一学生。**用中文沟通**，解释简短清楚
- 写代码前先在计划模式里给出方案，用户同意后再写
- 每个步骤结束时：跑测试 → 让用户按验收清单验收 → 更新 `docs/progress.md`（做了什么、下一步、踩过的坑）→ `git commit`
- **未经用户同意不 push**，不建远程仓库；引入新依赖、做大的结构调整前先问
- **不要打开 PNG 图片**（很费 token）。需要检查画面时用 `python -m shion --snapshot` 生成截图，只看截图
- 不要修改 `reference/`、`assets/sprites/raw/`；精灵图只能通过 `tools/process_sprites.py` 重新生成
- 主平台 Windows：路径用 `pathlib`；命令用 `.venv\Scripts\python`
- 测试：`.venv\Scripts\python -m pytest -q`。长日志写进文件，不要整段输出到对话里
- 每个大版本结束时调用 `reviewer` 子代理做审查

## 目录
- `docs/spec.md` 完整规格（窗口、交互、状态机、通信协议、开发步骤）
- `docs/progress.md` 进度与交接记录
- `shion/` 主程序 · `tests/` 测试 · `hooks/` CC hook 脚本
- `assets/sprites/` 12 张精灵图（448x512，已对齐）· `assets/lines/zh.json` 台词
- `tools/process_sprites.py` 素材处理脚本
