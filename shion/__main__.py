"""入口：python -m shion [--snapshot out.png [--state idle] [--bubble 文字]]"""
from __future__ import annotations

import argparse
import sys

from shion.pet_window import STATES


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shion", description="Shion 桌宠")
    p.add_argument("--snapshot", metavar="OUT.png", help="离屏渲染一帧存成 PNG 后退出")
    p.add_argument("--state", default="idle", choices=STATES, help="截图用的精灵（默认 idle）")
    p.add_argument("--bubble", default=None, help="截图里的气泡文字（第 5 步才实现）")
    args = p.parse_args(argv)

    from shion import app

    if args.snapshot:
        return app.snapshot(args.snapshot, args.state, args.bubble)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
