"""python -m v3proto; screenshots use exactly the preview renderer."""
import argparse
import os
from pathlib import Path

from PIL import Image


def save_snapshot(renderer, settings, pose, output, background="white"):
    from .render import to_pil
    rgba = to_pil(renderer.render(settings, pose))
    if background != "transparent":
        base = Image.new("RGBA", rgba.size, background)
        base.alpha_composite(rgba)
        rgba = base.convert("RGB")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--expression", choices=("smug", "neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"), default="smug")
    parser.add_argument("--scale", type=float, default=0.4)
    parser.add_argument("--time", type=float, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-animation", action="store_true")
    parser.add_argument("--underlays-only", action="store_true")
    parser.add_argument("--background", default="white")
    parser.add_argument("--benchmark", type=float, metavar="SECONDS")
    performance = parser.add_mutually_exclusive_group()
    performance.add_argument("--benchmark-pinch", action="store_true")
    performance.add_argument("--benchmark-head", choices=('knock','pat'))
    parser.add_argument("--head-preview", choices=('knock','combo','pat-left','pat-right'),
                        help="确定性敲摸截图；--time 为互动开始后的秒数")
    parser.add_argument("--benchmark-output", type=Path, default=Path("build/v3/step1/benchmark.json"))
    args = parser.parse_args(argv)
    if not 0.1 <= args.scale <= 2 or not 0 <= args.time <= 3600:
        parser.error("scale must be 0.1-2; time must be 0-3600 seconds")
    if args.benchmark is not None and not 1 <= args.benchmark <= 600:
        parser.error("benchmark must be 1-600 seconds")
    if args.head_preview and not args.snapshot:
        parser.error("--head-preview requires --snapshot")
    if args.snapshot or args.benchmark:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from .animation import Animator, Pose, Settings
    from .render import Renderer, Rig
    from .window import Preview, benchmark
    app = QApplication.instance() or QApplication([])
    settings = Settings(expression=args.expression, underlays_only=args.underlays_only)
    if args.no_animation:
        settings.breath = settings.blink = settings.sway = settings.pinch = False
    rig = Rig()
    if args.snapshot:
        animator = Animator(settings, args.seed, star_seed=args.seed)
        if args.head_preview:
            from .head_scenarios import head_scenario
            pose = head_scenario(animator, args.head_preview, args.time)
        else:
            pose = Pose() if args.no_animation else animator.advance(args.time)
        save_snapshot(Renderer(rig, args.scale), settings, pose, args.snapshot, args.background)
        print(f"snapshot: {args.snapshot}")
        return 0
    window = Preview(rig, settings, args.scale, args.seed)
    window.show()
    if args.benchmark:
        benchmark(window, args.benchmark, args.benchmark_output, app, args.benchmark_pinch, args.benchmark_head)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
