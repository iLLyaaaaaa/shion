"""运行期取证：源码下把 V3 全部状态、两侧、三个 scene、五种手势、周报、图标都跑一遍，
记录实际读过的 assets 文件（含 Qt 在 C++ 里按路径加载的）和实际加载过的 scipy / PIL 模块。

python -m tools.v3_runtime_trace OUT.json

文件：sys.addaudithook 的 open 事件（覆盖 open / Path.read_* / PIL.Image.open / numpy.load），
再给 QImage / QPixmap / QIcon 套一层子类记录按路径构造和 load / addFile（Qt 自己读文件时 Python 钩子看不到）。
必须在新进程里跑（scipy 模块清单要从干净解释器开始）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

opened: set[str] = set()
qt_opened: set[str] = set()


def _relative(path) -> str | None:
    try:
        resolved = Path(os.fspath(path)).resolve()
        return resolved.relative_to(ROOT).as_posix()
    except (TypeError, ValueError, OSError):
        return None


def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        rel = _relative(args[0] if not isinstance(args[0], bytes) else os.fsdecode(args[0]))
        if rel and rel.startswith("assets/"):
            opened.add(rel)


def _qt_record(path) -> None:
    if isinstance(path, (str, os.PathLike)):
        rel = _relative(path)
        if rel and rel.startswith("assets/"):
            qt_opened.add(rel)


def install_qt_recorders() -> None:
    from PySide6 import QtGui

    def wrap(cls, methods):
        def init(self, *args, **kwargs):
            if args:
                _qt_record(args[0])
            cls.__init__(self, *args, **kwargs)
        attrs = {"__init__": init}
        for name in methods:
            def method(self, path, *args, _name=name, **kwargs):
                _qt_record(path)
                return getattr(cls, _name)(self, path, *args, **kwargs)
            attrs[name] = method
        return type(cls.__name__, (cls,), attrs)

    QtGui.QImage = wrap(QtGui.QImage, ("load",))
    QtGui.QPixmap = wrap(QtGui.QPixmap, ("load",))
    QtGui.QIcon = wrap(QtGui.QIcon, ("addFile",))


def run_everything() -> dict:
    from shion import app
    from shion.pet_window import STATES

    ran = {"states": 0, "gestures": 0}
    for side in ("left", "right"):
        for state in STATES:
            app.render_snapshot(state=state, at=0.3, height=200, side=side)
            ran["states"] += 1
        for gesture in app.GESTURES:
            app.render_snapshot(state="idle", gesture=gesture, at=0.4, height=200, side=side)
            ran["gestures"] += 1
    return ran


def run_weekly_and_icon() -> None:
    from PySide6.QtWidgets import QApplication
    from shion.icons import application_icon
    from shion.weekly import preview
    from shion.weekly_ui import render_card

    QApplication.instance() or QApplication([])
    application_icon()
    for lang in ("zh", "en", "ja"):
        render_card(preview(lang, True), True)
    # 每个称号对应的立绘都要读到
    import json as _json
    rules = _json.loads((ROOT / "assets/weekly_titles.json").read_text(encoding="utf-8"))
    for rule in rules:
        data = preview("zh", True)
        data["title"] = {**data["title"], "sprite": rule["sprite"]}
        render_card(data, True)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    sys.addaudithook(_audit)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    install_qt_recorders()
    ran = run_everything()
    run_weekly_and_icon()
    modules = sorted(sys.modules)
    result = {
        "ran": ran,
        "files": sorted(opened | qt_opened),
        "qt_files": sorted(qt_opened),
        "scipy_modules": [m for m in modules if m == "scipy" or m.startswith("scipy.")],
        "pil_modules": [m for m in modules if m == "PIL" or m.startswith("PIL.")],
    }
    Path(argv[0]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[0]).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"states={ran['states']} gestures={ran['gestures']} files={len(result['files'])} "
          f"qt_files={len(result['qt_files'])} scipy_modules={len(result['scipy_modules'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
