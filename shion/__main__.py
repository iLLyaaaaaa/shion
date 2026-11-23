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
    if argv[:1] == ["--chat-mcp"]:
        from shion.chat_mcp import main as chat_mcp
        return chat_mcp(argv[1:])
    if argv[:1] == ["--statusline"]:
        from hooks.shion_statusline import main as statusline
        return statusline(argv[1:])
    if argv[:1] == ["--codex-observer"]:
        from shion.codex_mcp import main as observe
        return observe(argv[1:])
    if argv[:1] == ["--hook"]:
        from hooks.shion_hook import run_hook
        return run_hook(argv[1:])
    if argv[:1] == ["--console-send"]:
        from shion.console_send import main as console_send
        return console_send(argv[1:])
    if argv[:1] == ["--self-check-v3"]:
        from shion.bundle_check_v3 import main as check_v3
        return check_v3(argv[1:])
    if argv[:1] == ["--self-check-connection"]:
        from shion.bundle_check import main as check_connection
        return check_connection(argv[1:])

    from shion.pet_window import STATES, PROP_STATES

    p = argparse.ArgumentParser(prog="shion", description="Shion 桌宠")
    p.add_argument("--snapshot", metavar="OUT.png", help="离屏渲染一帧存成 PNG 后退出")
    p.add_argument("--weekly-preview", action="store_true", help="配合 --snapshot：用合成数据渲染周报")
    p.add_argument("--weekly-no-usage", action="store_true", help="周报预览：隐藏用量与价格")
    p.add_argument("--weekly-no-branding", action="store_true", help="周报预览：隐藏项目链接")
    p.add_argument("--icon-preview", action="store_true", help="配合 --snapshot：各尺寸图标的浅色/深色预览")
    p.add_argument("--state", default="idle", choices=STATES + list(PROP_STATES), help="截图用的精灵（默认 idle）")
    p.add_argument("--from-state", choices=STATES + list(PROP_STATES), help="截图用：从这张精灵交叉淡化到 --state")
    p.add_argument("--bubble", default=None, help="截图里头顶的气泡文字（--at 是打字进度，不给则显示完整）")
    p.add_argument("--at", type=float, default=0.0, help="截图用：切到该状态后第几秒的那一帧")
    p.add_argument("--height", type=int, choices=[160, 200, 260, 320], default=200, help="截图用：本体高度")
    p.add_argument("--activity", choices=["quiet", "normal", "lively"], default="normal", help="截图用：活跃度")
    p.add_argument("--squash", choices=["click", "land"], default=None, help="截图用：0 秒时触发压扁")
    p.add_argument("--badge", action="store_true", help="截图用：画出暂停文字标签")
    p.add_argument("--chips", choices=["demo"], help="截图用：用合成任务绘制标签")
    p.add_argument("--chips-side", choices=["left", "right"], help="截图用：任务标签所在侧（默认右侧）")
    p.add_argument("--chips-overlays", choices=["pause", "checkpoints"], help="截图用：与其他提示共存")
    p.add_argument("--lang", default="zh", help="截图用：气泡字体按这个语言的 font_fallback 选（zh/en/ja…）")
    p.add_argument("--panel", choices=["permission", "input", "dialogue", "snacks", "eating", "about", "connection", "budget"], default=None,
                   help="截图用：授权、检查点停下、反馈、对话首页、零食列表或吃零食效果")
    p.add_argument("--with-pet", action="store_true", help="面板截图同时绘制诗音，检查相邻位置")
    p.add_argument("--panel-text", default="git status", help="截图用：同意/否决面板里显示的内容")
    p.add_argument("--panel-more", type=int, default=0, help="截图用：“还有 N 个”")
    p.add_argument("--panel-expand", action="store_true", help="截图用：展开长内容")
    motion = p.add_mutually_exclusive_group()
    motion.add_argument("--jump", action="store_true", help="截图用：0 秒时触发原地跳")
    motion.add_argument("--nod", action="store_true", help="截图用：working 在 0 秒点头，配合 --at 0～0.4")
    motion.add_argument("--gesture", choices=["pinch", "pat", "knock", "tickle", "lift"],
                        help="截图用：捏脸 / 摸头 / 敲头 / 挠痒 / 拎起，让动画器走到手势的第 --at 秒")
    p.add_argument("--side", choices=["left", "right"], default=None, help="截图用：鼓脸颊的一侧（不自动换边）")
    args = p.parse_args(argv)

    if args.chips and (not args.snapshot or args.panel or args.weekly_preview or args.icon_preview):
        p.error("--chips requires a pet --snapshot")
    if (args.chips_side or args.chips_overlays) and not args.chips:
        p.error("--chips-side and --chips-overlays require --chips")

    from shion import app

    if args.weekly_preview:
        if not args.snapshot:
            p.error("--weekly-preview requires --snapshot")
        from PySide6.QtWidgets import QApplication
        from shion.weekly import preview
        from shion.weekly_ui import render_card
        application = QApplication.instance() or QApplication([])
        image = render_card(preview(args.lang, not args.weekly_no_usage), not args.weekly_no_branding)
        return 0 if image.save(args.snapshot, "PNG") else 1

    if args.snapshot and args.icon_preview:
        return app.snapshot_icon_preview(args.snapshot)
    if args.snapshot and args.panel:
        return app.snapshot_panel(args.snapshot, args.panel, args.panel_text, args.lang,
                                  args.panel_more, args.panel_expand, args.with_pet)
    if args.snapshot:
        return app.snapshot(args.snapshot, args.state, args.bubble, args.at, args.squash, args.lang,
                            args.from_state, jump=args.jump, badge=args.badge,
                            height=args.height, activity=args.activity, nod=args.nod,
                            gesture=args.gesture, side=args.side, chips=args.chips,
                            chips_side=args.chips_side, chips_overlays=args.chips_overlays)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
