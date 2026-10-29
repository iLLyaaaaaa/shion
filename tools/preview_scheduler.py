"""Isolated native Qt snapshots of the V2 adapter, not client acceptance.

Run: .venv/Scripts/python tools/preview_scheduler.py --out .venv/preview-run/v2-visual --scale 1.5
No listeners, Hooks, MCP installation, real user data, or installed package.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scale", choices=("1", "1.5", "2"), default="1")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    isolated = out / "isolated"
    for key in ("HOME", "USERPROFILE", "APPDATA", "CODEX_HOME", "SHION_DATA_DIR"):
        os.environ[key] = str(isolated / key)
    os.environ["QT_SCALE_FACTOR"] = os.environ.get("SHION_PREVIEW_QT_FACTOR", "1")
    os.environ["QT_SCREEN_SCALE_FACTORS"] = args.scale
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_QPA_PLATFORM"] = "windows"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
    from PySide6.QtWidgets import QApplication, QWidget
    from shion.app import SnapshotScene, render_widget_image
    from shion.chatgpt import ChatGPTConnection
    from shion.controller import PetController
    from shion.events import Observation
    from shion.lines import Lines
    from shion.state import PetState, SaveData, SaveScheduler
    from shion.tasks import TaskLedger

    # Every widget remains off desktop while using native font/layout rendering.
    original_show = QWidget.show
    def hidden_show(widget):
        widget.setAttribute(Qt.WA_DontShowOnScreen)
        original_show(widget)
    QWidget.show = hidden_show
    app = QApplication.instance() or QApplication([])
    actual = app.primaryScreen().devicePixelRatio()
    if abs(actual - float(args.scale)) > 0.01:
        if "SHION_PREVIEW_QT_FACTOR" in os.environ:
            raise RuntimeError("Qt did not honor the requested preview DPR")
        child_env = dict(os.environ, SHION_PREVIEW_QT_FACTOR=str(float(args.scale) / actual))
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                               "--scale", args.scale], env=child_env, check=False).returncode
    records = []
    sheet = QImage(1100 * 2, 430 * 3 * 2, QImage.Format_ARGB32_Premultiplied)
    sheet.setDevicePixelRatio(2)
    sheet.fill(QColor("#e9e5df"))
    painter = QPainter(sheet)
    try:
        for row, lang in enumerate(("zh", "en", "ja")):
            with SnapshotScene(seed=7, scale=2) as scene:
                now = datetime(2026, 10, 29, 12)
                data = SaveData(v2_scheduler_enabled=True, connection_prompt="skipped")
                save = SaveScheduler(isolated / lang / "state.json", data)
                state = PetState(data, now, on_change=save.mark_dirty)
                ctl = PetController(scene.win, state, save, lines=Lines(lang), now_fn=lambda: now,
                                    say=lambda *_: None, autostart=False)
                ctl.chatgpt = ChatGPTConnection(isolated / lang, isolated / "codex")
                ctl.chatgpt.ledger = TaskLedger(clock=lambda: scene.time[0])
                # build_menu only inspects startup; never access the real registry.
                from types import SimpleNamespace
                ctl.startup.inspect = lambda: SimpleNamespace(state="disabled", detail="", enabled=False)
                try:
                    ctl.observe_v2(Observation("UserPromptSubmit", "synthetic", "turn"))
                    ctl.observe_v2(Observation("PermissionRequest", "synthetic", "turn"))
                    ctl.hub.permissions.open("Read", "synthetic permission / 模拟授权 / テスト", session="claude")
                    ctl.tick()
                    menu = ctl.build_menu()
                    menu.ensurePolished()
                    menu.adjustSize()
                    panel = ctl._perm_panel
                    app.processEvents()
                    pet = scene.render()
                    panel_img = render_widget_image(panel, 2)
                    menu_img = render_widget_image(menu, 2)
                    y = row * 430
                    painter.setPen(QColor("#242020"))
                    painter.drawText(QRect(15, y + 5, 1070, 30), lang + " / Qt scale " + args.scale + " / " + ctl.v2.text(ctl.lines.ui))
                    painter.drawImage(QPoint(15, y + 65), pet)
                    painter.drawImage(QPoint(300, y + 45), panel_img)
                    painter.drawImage(QPoint(720, y + 45), menu_img)
                    assert panel.height() < 380 and panel.width() < 410
                    assert menu.width() < 360 and menu.height() < 380
                    assert panel._observation_hint.height() >= panel._observation_hint.heightForWidth(panel._observation_hint.width())
                    records.append(dict(language=lang, dpr=scene.win.devicePixelRatioF(),
                        panel=[panel.width(), panel.height()], menu=[menu.width(), menu.height()],
                        font_families=len(QFontDatabase.families()), state=ctl.v2.display.state))
                    menu.deleteLater()
                finally:
                    ctl.dispose()
    finally:
        painter.end()
        QWidget.show = original_show
    target = out / "scheduler-snapshot.png"
    if not sheet.save(str(target)):
        raise RuntimeError("snapshot save failed")
    (out / "checks.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
