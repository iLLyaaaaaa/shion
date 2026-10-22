"""把 Shion 的 Claude Code hooks 合并进 settings 文件。

用法：python tools/install_hooks.py [--settings PATH]
默认写用户级 ~/.claude/settings.json；开发阶段请用
--settings .claude/settings.local.json（项目级）。
默认用户级安装也会备份并移除本项目的旧 Shion hooks，避免重复事件；
显式 --settings 只修改指定文件。
检查点的转圈文字（statusMessage）按诗音存档语言写入；在诗音里换语言后重跑一次才会跟着变，
也可以用 --lang zh|en|ja 指定。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooks_config  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", help="settings 文件路径（默认 ~/.claude/settings.json）")
    ap.add_argument("--lang", choices=hooks_config.LANGS, help="转圈文字的语言（默认跟随诗音存档）")
    args = ap.parse_args()
    sys.exit(hooks_config.run("install", args.settings, lang=args.lang))
