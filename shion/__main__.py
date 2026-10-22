"""入口：python -m shion [--snapshot out.png [--state idle] [--bubble 文字]]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 注册表没有工作目录；源码入口也支持 pythonw.exe <绝对路径>/shion/__main__.py。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    from shion.runtime import prepare_standard_streams
    prepare_standard_streams()
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--hook"]:
        from hooks.shion_hook import run_hook
        return run_hook(argv[1:])
    if argv[:1] == ["--console-send"]:
        from shion.console_send import main as console_send
        return console_send(argv[1:])
    if argv[:1] == ["--self-check-connection"]:
        from shion.bundle_check import main as check_connection
        return check_connection(argv[1:])

    from shion.pet_window import STATES, PROP_STATES

    p = argparse.ArgumentParser(prog="shion", description="Shion 桌宠")
    p.add_argument("--snapshot", metavar="OUT.png", help="离屏渲染一帧存成 PNG 后退出")
    p.add_argument("--state", default="idle", choices=STATES + list(PROP_STATES), help="截图用的精灵（默认 idle）")
    p.add_argument("--from-state", choices=STATES + list(PROP_STATES), help="截图用：从这张精灵交叉淡化到 --state")
    p.add_argument("--bubble", default=None, help="截图里头顶的气泡文字（--at 是打字进度，不给则显示完整）")
    p.add_argument("--at", type=float, default=0.0, help="截图用：切到该状态后第几秒的那一帧")
    p.add_argument("--height", type=int, choices=[160, 200, 260, 320], default=200, help="截图用：本体高度")
    p.add_argument("--activity", choices=["quiet", "normal", "lively"], default="normal", help="截图用：活跃度")
    p.add_argument("--squash", choices=["click", "land"], default=None, help="截图用：0 秒时触发压扁")
    p.add_argument("--badge", action="store_true", help="截图用：画出暂停文字标签")
    p.add_argument("--lang", default="zh", help="截图用：气泡字体按这个语言的 font_fallback 选（zh/en/ja…）")
    p.add_argument("--panel", choices=["permission", "input", "dialogue", "snacks", "eating", "about", "connection"], default=None,
                   help="截图用：授权、检查点停下、反馈、对话首页、零食列表或吃零食效果")
    p.add_argument("--with-pet", action="store_true", help="面板截图同时绘制诗音，检查相邻位置")
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
    motion.add_argument("--weight-shift", choices=["crouch", "left", "right"], help="截图用：0 秒触发换重心，配合 --at 0～0.6")
    motion.add_argument("--nod", action="store_true", help="截图用：working 在 0 秒点头，配合 --at 0～0.4")
    motion.add_argument("--desk-blink", choices=["single", "double"], help="截图用：desk 在 0 秒眨眼")
    args = p.parse_args(argv)

    from shion import app

    if args.snapshot and args.panel:
        return app.snapshot_panel(args.snapshot, args.panel, args.panel_text, args.lang,
                                  args.panel_more, args.panel_expand, args.with_pet)
    if args.snapshot:
        return app.snapshot(args.snapshot, args.state, args.bubble, args.at, args.squash, args.lang,
                            args.from_state, jump=args.jump, turn=args.turn, drag=args.drag,
                            face=args.face, cheek=args.cheek, tickle=args.tickle, badge=args.badge,
                            height=args.height, activity=args.activity, weight_shift=args.weight_shift,
                            nod=args.nod, desk_blink=args.desk_blink)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
