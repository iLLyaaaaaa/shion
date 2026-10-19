"""把 Shion 的 Claude Code hooks 合并进 settings 文件。

用法：python tools/install_hooks.py [--settings PATH]
默认写用户级 ~/.claude/settings.json；开发阶段请用
--settings .claude/settings.local.json（项目级）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooks_config  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", help="settings 文件路径（默认 ~/.claude/settings.json）")
    sys.exit(hooks_config.run("install", ap.parse_args().settings))
