"""入口：python -m shion [--snapshot out.png [--state idle] [--bubble 文字]]"""
from __future__ import annotations

import argparse
import sys

from shion.pet_window import STATES, PROP_STATES


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shion", description="Shion 桌宠")
    p.add_argument("--snapshot", metavar="OUT.png", help="离屏渲染一帧存成 PNG 后退出")
    p.add_argument("--state", default="idle", choices=STATES + list(PROP_STATES), help="截图用的精灵（默认 idle）")
    p.add_argument("--from-state", choices=STATES + list(PROP_STATES), help="截图用：从这张精灵交叉淡化到 --state")
    p.add_argument("--bubble", default=None, help="截图里头顶的气泡文字（--at 是打字进度，不给则显示完整）")
    p.add_argument("--at", type=float, default=0.0, help="截图用：切到该状态后第几秒的那一帧")
    p.add_argument("--squash", choices=["click", "land"], default=None, help="截图用：0 秒时触发压扁")
    p.add_argument("--badge", action="store_true", help="截图用：画出暂停文字标签")
    p.add_argument("--lang", default="zh", help="截图用：气泡字体按这个语言的 font_fallback 选（zh/en/ja…）")
    p.add_argument("--panel", choices=["permission", "input", "dialogue", "snacks", "eating"], default=None,
                   help="截图用：授权、检查点停下、反馈、对话首页、零食列表或吃零食效果")
    p.add_argument("--panel-text", default="git status", help="截图用：同意/否决面板里显示的内容")
    p.add_argument("--panel-more", type=int, default=0, help="截图用：“还有 N 个”")
    p.add_argument("--panel-expand", action="store_true", help="截图用：展开长内容")
    motion = p.add_mutually_exclusive_group()
    motion.add_argument("--jump", action="store_true", help="截图用：0 秒时触发原地跳")
    motion.add_argument("--turn", action="store_true", help="截图用：转一圈，配合 --at 检查八帧")
    motion.add_argument("--face", choices=["left", "right"], help="截图用：朝向鼠标的左右侧身")
    motion.add_argument("--cheek", choices=["left", "right", "release"], help="截图用：捏脸与松手")
    motion.add_argument("--tickle", action="store_true", help="截图用：持续挠痒痒")
    motion.add_argument("--drag", action="store_true", help="截图用：循环拖动帧，配合 --at 检查帧序列")
    args = p.parse_args(argv)

    from shion import app

    if args.snapshot and args.panel:
        return app.snapshot_panel(args.snapshot, args.panel, args.panel_text, args.lang,
                                  args.panel_more, args.panel_expand)
    if args.snapshot:
        return app.snapshot(args.snapshot, args.state, args.bubble, args.at, args.squash, args.lang,
                            args.from_state, jump=args.jump, turn=args.turn, drag=args.drag,
                            face=args.face, cheek=args.cheek, tickle=args.tickle, badge=args.badge)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
