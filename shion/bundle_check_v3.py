"""打包自检：V3 渲染链路（冻结 exe 里 scipy / Pillow / V3 素材是否齐全可用）。

shion.exe --self-check-v3 OUT.json
离屏、假时钟、同步预热执行器；只读包内素材，不碰存档、端口和任何用户配置。结果写成 JSON，任何一项不满足就抛错（退出码 1）。
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

import numpy as np

SCENES = ("bed", "desk", "collapse")


def _array(image) -> np.ndarray:
    from PySide6.QtGui import QImage
    im = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())
    return a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).astype(np.int16)


def _different(a: np.ndarray, b: np.ndarray) -> int:
    """两帧不同像素数（尺寸不同直接算全不同）。"""
    if a.shape != b.shape:
        return int(max(a.shape[0] * a.shape[1], b.shape[0] * b.shape[1]))
    return int((np.abs(a - b).max(axis=2) > 8).sum())


def run_checks() -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    opened: set[str] = set()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)).resolve()

    def audit(event, args):
        if event == "open" and args and isinstance(args[0], (str, os.PathLike)):
            try:
                rel = Path(os.fspath(args[0])).resolve().relative_to(base).as_posix()
            except (ValueError, OSError):
                return
            if rel.startswith(("assets/sprites/", "assets/weekly/")) or rel.startswith("_internal/assets/sprites/"):
                opened.add(rel)

    sys.addaudithook(audit)
    checks: list[str] = []

    def require(condition, name):
        if not condition:
            raise RuntimeError(f"V3 自检失败：{name}")
        checks.append(name)

    import PIL
    import scipy
    from scipy import ndimage  # noqa: F401 - 真的导入，缺 DLL 会在这里失败
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    import shion.v3_window as v3_window
    from shion import app
    from shion.pet_window import STATES
    from shion.v3_prewarm import InlineExecutor

    v3_window.PREWARM_EXECUTOR = InlineExecutor()
    require(True, "imports")

    report: dict = {"scipy": scipy.__version__, "pillow": PIL.__version__, "states": len(STATES)}

    # 1. 全部状态各渲染一帧非空
    left = app.SnapshotScene("idle", 200, side="left")
    try:
        rest = None
        for index, state in enumerate(STATES):
            left.win.set_state(state, animate=False)
            left.advance_to(0.3 + index * 5.0)
            frame = _array(left.render())
            require(frame.size > 0 and int((frame[..., 3] > 0).sum()) > 1000, f"render-{state}")
        left.win.set_state("idle", animate=False)
        left.advance_to(200.0)
        rest = _array(left.render())

        # 2. 捏脸：按下外拉后帧与静止不同；松手回弹后回到静止附近
        app.apply_snapshot_gesture(left.win, "pinch", 0.3)
        left.advance_to(left.time[0] - 100.0 + 0.3)  # 与 app._render_snapshot 一致：做完手势再走到第 at 秒
        pinched = _array(left.render())
        moved = _different(rest, pinched)
        # 待机的呼吸 / 眨眼本身就会让两帧差一万像素左右，所以“真的拉伸了”以动画器的姿态为准，帧差只做兜底
        require(moved > 200 and max(abs(v) for v in left.win._v3_pose.pinch_delta) > 30, "pinch-differs")
        animator = left.win._v3_animator
        animator.release(now=animator.clock)
        for _ in range(60):  # 按 0.1 秒一步走 6 秒（一步跳太大，弹簧积分不收敛）
            left.advance_to(left.time[0] - 100.0 + 0.1)
        after = _array(left.render())
        require(max(abs(v) for v in left.win._v3_pose.pinch_delta) < 1.0, "pinch-returns")  # 阻尼回弹，6 秒后 <1 像素
        report["pinch_pixels"] = {"pinched": moved, "after_release": _different(rest, after)}
        left.win.set_state("idle", animate=False)
        left.advance_to(210.0)
        left_neutral = _array(left.render())
        left_rig = left.win._v3_rig if hasattr(left.win, "_v3_rig") else v3_window.shared_rig("left")
        left_visible, left_foot = left_rig.v3_visible, left_rig.v3_foot

        # 4. scene：三个 scene 真的载入、窗口加宽（不是站姿回退）
        widths = {}
        normal = left.win.normal_width
        for name in SCENES:
            left.win.set_state(name, animate=False)
            left.advance_to(220.0 + len(widths) * 3)
            require(left.win._v3_scene_active() is not None, f"scene-{name}-loaded")
            # 窗口宽度按 scene 角色半宽放大；desk 比站姿窄，不会变宽，所以按公式核对而不是一律“变宽”
            from shion import v3_scene
            shown = left.win._v3_scene_shown
            expected = max(normal, math.ceil(2 * v3_scene.extra_half_width(shown) * left.win._v3_scale))
            require(left.win._sw == expected, f"scene-{name}-width")
            widths[name] = left.win._sw
        report["scene_widths"] = {**widths, "standing": normal}
    finally:
        left.close()

    # 3. 换边：右侧 neutral 与左侧不同，可见高度、脚底一致；丢掉一侧后 _RIGS 不含它
    right = app.SnapshotScene("idle", 200, side="right")
    try:
        right.advance_to(1.0)
        right_neutral = _array(right.render())
        require(_different(left_neutral, right_neutral) > 200, "sides-differ")
        right_rig = v3_window.shared_rig("right")
        require(right_rig.v3_visible[3] - right_rig.v3_visible[1] == left_visible[3] - left_visible[1]
                and abs(right_rig.v3_foot[1] - left_foot[1]) < 0.5, "sides-same-height-and-foot")
        require("right" in v3_window._RIGS, "right-rig-cached")
        right.win._v3_drop_side("right")
        require("right" not in v3_window._RIGS, "drop-side-releases-rig")
    finally:
        right.close()

    report["opened_assets"] = sorted(opened)
    report["opened_count"] = len(opened)
    report["scipy_modules"] = sorted(m for m in sys.modules if m == "scipy" or m.startswith("scipy."))
    report["checks"] = checks
    report["frozen"] = bool(getattr(sys, "frozen", False))
    return report


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 1:
            raise ValueError("需要一个输出 JSON 路径")
        result = run_checks()
        Path(argv[0]).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "checks": len(result["checks"]), "opened": result["opened_count"]}))
    return 0
