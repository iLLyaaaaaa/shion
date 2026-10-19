"""从 settings 文件里移除 Shion 的 hooks，其他配置原样保留。

用法：python tools/uninstall_hooks.py [--settings PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooks_config  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settings", help="settings 文件路径（默认 ~/.claude/settings.json）")
    sys.exit(hooks_config.run("uninstall", ap.parse_args().settings))
