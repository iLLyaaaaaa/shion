"""R2：V3 是唯一外观。默认窗口、--renderer 已删除、v2.2.0 旧存档、其它入口照常。"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt

from shion import state as S
from shion.pet_window import MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X
from tests.test_v3_display import qapp  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


def old_save(**window) -> dict:
    """v2.2.0 形状的存档：没有 v3_lift_hint_shown，窗口位置和固定表情照旧。"""
    raw = S.SaveData().to_dict()
    del raw["v3_lift_hint_shown"]
    raw["window"] = dict(window)
    raw["fixed_expression"] = "sleep"
    return raw


class Env:
    """真实的 V3 窗口 + 控制器，读一份磁盘上的旧存档。"""

    def __init__(self, tmp_path, raw):
        from shion.controller import PetController
        from shion.effects import HeartOverlay
        from shion.lines import Lines
        from shion.v3_window import V3PetWindow
        self.path = tmp_path / "state.json"
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        self.mono, self.said, self.now = [100.0], [], datetime(2026, 11, 17, 15, 0, 0)
        self.data = S.load(self.path)
        self.scheduler = S.SaveScheduler(self.path, self.data)
        self.state = S.PetState(self.data, self.now, on_change=self.scheduler.mark_dirty)
        self.win = V3PetWindow(height=self.data.window.get("height", 200), clock=lambda: self.mono[0],
                               autostart=False, debug=False, pixel_ratio=1.0)
        self.win.setAttribute(Qt.WA_DontShowOnScreen)
        self.overlay = HeartOverlay(clock=lambda: self.mono[0], autostart=False)
        self.ctl = PetController(self.win, self.state, self.scheduler, lines=Lines(), overlay=self.overlay,
                                 now_fn=lambda: self.now, say=self.said.append, autostart=False)

    def close(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        self.ctl.dispose()
        self.overlay.close()
        self.overlay.deleteLater()
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_no_arguments_start_the_v3_window(qapp, monkeypatch, tmp_path):  # noqa: F811
    from shion import app
    from shion.__main__ import main
    from shion.v3_window import V3PetWindow

    class Reached(Exception):
        pass

    seen = {}

    def construct(self, *args, **kwargs):
        seen.update(cls=type(self), kwargs=kwargs)
        raise Reached

    previous = (qapp.applicationName(), qapp.applicationVersion(), qapp.windowIcon(),
                qapp.quitOnLastWindowClosed())
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app.SingleInstance, "acquire", lambda _self: True)
    monkeypatch.setattr(app, "setup_logging", lambda *_a: None)
    monkeypatch.setattr(V3PetWindow, "__init__", construct)
    try:
        with pytest.raises(Reached):
            main([])
    finally:
        qapp.setApplicationName(previous[0])
        qapp.setApplicationVersion(previous[1])
        qapp.setWindowIcon(previous[2])
        qapp.setQuitOnLastWindowClosed(previous[3])
    assert seen["cls"] is V3PetWindow
    assert seen["kwargs"]["height"] == 200 and "initial_side" in seen["kwargs"]
    assert not hasattr(app, "window_class")


def test_snapshot_scene_and_panel_use_the_v3_window(qapp):  # noqa: F811
    from shion.app import SnapshotScene
    from shion.v3_window import V3PetWindow
    with SnapshotScene("idle", 200) as scene:
        assert type(scene.win) is V3PetWindow


@pytest.mark.parametrize("extra", (["--renderer", "v3"], ["--renderer", "v2"],
                                   ["--snapshot", "x.png", "--renderer", "v3"]))
def test_renderer_argument_is_rejected(extra, capsys):
    from shion.__main__ import main
    with pytest.raises(SystemExit) as stop:
        main(extra)
    assert stop.value.code == 2
    assert "--renderer" in capsys.readouterr().err


def test_v220_save_loads_and_the_window_stays_on_screen(qapp, tmp_path):  # noqa: F811
    screen = qapp.primaryScreen().availableGeometry()
    # 没有 y 的旧档：脚底贴底；x 超出右边：夹回屏内。
    env = Env(tmp_path, old_save(x=screen.right() - 5, height=260))
    try:
        assert env.data.v3_lift_hint_shown is False and env.data.fixed_expression == "sleep"
        env.ctl.restore_position()
        env.ctl.sync()
        env.mono[0] += .5
        env.win.advance_to(env.mono[0])
        w = env.win
        assert w.sprite_height == 260
        assert w.x() + MARGIN_X >= screen.left() and w.x() + w.width() - MARGIN_X <= screen.right() + 1
        assert w.y() + w.height() - MARGIN_BOTTOM == screen.bottom() + 1
        assert not w.is_floating
    finally:
        env.close()
    # 有 y 的存档（悬空）：纵向保留，但不超出屏幕上下沿。
    env = Env(tmp_path, old_save(x=screen.left() + 40, y=screen.bottom() + 5000, height=200))
    try:
        env.ctl.restore_position()
        w = env.win
        assert QRect(screen).adjusted(-MARGIN_X, -MARGIN_TOP, MARGIN_X, MARGIN_BOTTOM).contains(w.geometry())
        assert w.y() + w.height() - MARGIN_BOTTOM == screen.bottom() + 1
    finally:
        env.close()


def test_old_save_gets_the_lift_hint_once(qapp, tmp_path, monkeypatch):  # noqa: F811
    import shion.controller as C
    timers = []
    monkeypatch.setattr(C.QTimer, "singleShot", staticmethod(lambda ms, fn: timers.append((ms, fn))))
    raw = old_save(height=200)
    raw["fixed_expression"] = None
    env = Env(tmp_path, raw)
    try:
        env.ctl.arm_lift_hint()
        assert [ms for ms, _ in timers] == [env.ctl.LIFT_HINT_DELAY_MS]
        timers.pop()[1]()
        assert env.said and env.said[-1] in env.ctl.lines._lines["v3_lift_hint"]
        assert env.data.v3_lift_hint_shown is True
        env.scheduler.flush()
    finally:
        env.close()
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["v3_lift_hint_shown"] is True
    env = Env(tmp_path, saved)  # 再次启动：已经说过，不再安排
    try:
        env.ctl.arm_lift_hint()
        assert not timers and not env.said
    finally:
        env.close()


def run_entry(args, tmp_path, stdin=b""):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from shion.__main__ import main
result = main({args!r})
assert not any(key.startswith('PySide6.Qt') for key in sys.modules), 'Qt imported'
assert 'shion.v3_window' not in sys.modules and 'scipy' not in sys.modules, 'V3 imported'
sys.exit(result)
"""
    env = {**os.environ, "SHION_PORT": "1", "SHION_DATA_DIR": str(tmp_path)}
    return subprocess.run([sys.executable, "-c", code], env=env, input=stdin, capture_output=True,
                          timeout=30, cwd=tmp_path)


def test_hook_entry_keeps_its_command_line(monkeypatch, tmp_path):
    """--hook <事件名>：在 argparse 之前分发，参数原样交给 hook，不加载 Qt 和 V3。"""
    import hooks.shion_hook as hook
    from shion.__main__ import main
    got = []
    monkeypatch.setattr(hook, "run_hook", lambda argv: got.append(argv) or 0)
    for args in (["Stop"], ["PreToolUse"], ["PermissionRequest"], ["SessionStart", "--renderer", "v3"]):
        assert main(["--hook", *args]) == 0
        assert got[-1] == args
    result = run_entry(["--hook", "Stop"], tmp_path, b"{}")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_chat_mcp_and_codex_observer_entries_still_start(tmp_path):
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode() + b"\n"
    result = run_entry(["--chat-mcp"], tmp_path, init)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    reply = json.loads(result.stdout.splitlines()[0])
    assert reply["id"] == 1 and "result" in reply
    result = run_entry(["--codex-observer", "--data-dir", str(tmp_path)], tmp_path, init)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    reply = json.loads(result.stdout.splitlines()[0])
    assert reply["id"] == 1 and "result" in reply


def test_snapshot_entry_renders_the_v3_pet_and_a_panel(qapp, tmp_path):  # noqa: F811
    import numpy as np
    from PIL import Image
    from shion.__main__ import main
    for name, args in (("pet.png", ["--state", "happy"]),
                       ("panel.png", ["--panel", "permission", "--with-pet"])):
        out = tmp_path / name
        assert main(["--snapshot", str(out), *args]) == 0
        with Image.open(out) as im:
            assert np.asarray(im.convert("RGBA"))[..., 3].any()
