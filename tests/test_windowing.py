"""置顶存档、实时切换、提醒前移、面板避让及原生 Windows 层级。"""
import ctypes
import sys

import pytest
from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

from shion import __version__
from shion.bubble import BubbleWindow
from shion.state import SaveData, load
from shion.windowing import place_dialog, raise_without_activation
from tests.test_controller import Env, env, qapp, find_action


@pytest.mark.parametrize("raw,expected", [({}, True), ({"always_on_top": False}, False),
    ({"always_on_top": True}, True), ({"always_on_top": 0}, True),
    ({"always_on_top": "false"}, True), ({"always_on_top": None}, True)])
def test_save_defaults_and_validation(raw, expected):
    data = SaveData.from_dict(raw)
    assert data.always_on_top is expected
    assert SaveData.from_dict(data.to_dict()).always_on_top is expected


def test_startup_reads_saved_switch_and_flushes_toggle(qapp, tmp_path):
    e = Env(tmp_path, SaveData(always_on_top=False))
    try:
        assert not e.win.windowFlags() & Qt.WindowStaysOnTopHint
        assert not e.overlay.windowFlags() & Qt.WindowStaysOnTopHint
        e.ctl.set_always_on_top(True)
        e.scheduler.flush()
        assert load(e.path).always_on_top
        e.ctl.set_always_on_top(False)
        e.scheduler.flush()
        assert not load(e.path).always_on_top
    finally:
        e.close()


@pytest.mark.parametrize("lang,label", [("zh", "置于最上层"), ("en", "Always on top"),
                                        ("ja", "最前面に表示")])
def test_menu_is_checkable_live_and_translated(env, lang, label):
    env.ctl.set_language(lang)
    menu = env.ctl.build_menu()
    action = find_action(menu, label)
    assert action.isCheckable() and action.isChecked()
    action.trigger()
    assert not env.data.always_on_top
    assert not env.win.windowFlags() & Qt.WindowStaysOnTopHint
    menu.deleteLater()


@pytest.mark.parametrize("visible", [False, True])
def test_switch_preserves_geometry_mask_flags_attributes_and_visibility(env, visible):
    bubble = env.ctl.bubble = BubbleWindow(autostart=False)
    try:
        env.win.move(130, 170)
        if visible:
            env.win.show()
            bubble.follow(env.win.body_rect())
            bubble.say("test")
            env.overlay.burst(env.win.head_anchor())
        windows = [env.win, bubble, env.overlay]
        before = [(w.geometry(), w.mask(), w.windowFlags()) for w in windows]
        for on in (False, True, False):
            env.ctl.set_always_on_top(on)
            for w, (geometry, mask, flags) in zip(windows, before):
                assert w.geometry() == geometry and w.mask() == mask
                assert w.isVisible() == visible
                assert bool(w.windowFlags() & Qt.WindowStaysOnTopHint) == on
                assert w.windowFlags() & ~Qt.WindowStaysOnTopHint == flags & ~Qt.WindowStaysOnTopHint
                assert w.testAttribute(Qt.WA_ShowWithoutActivating)
                assert w.testAttribute(Qt.WA_TranslucentBackground)
    finally:
        bubble.close()
        env.ctl.bubble = None


def test_late_created_effects_badge_and_dialogs_follow_separate_policies(env):
    env.ctl.set_always_on_top(False)
    env.win.show()
    env.win.set_paused_badge(True)
    env.ctl.choose_dialogue("snacks", env.ctl.menu_content.snacks[0].id)
    env.ctl.open_bad_feedback()
    env.ctl.open_dialogue()
    rid = env.ctl.hub.permissions.open("Bash", "echo ok")
    env.ctl._sync_permission()
    assert env.ctl._perm_panel.request_id == rid
    for on in (False, True, False):
        env.ctl.set_always_on_top(on)
        for w in (env.win._pause_badge, env.ctl._crumbs, env.overlay):
            assert bool(w.windowFlags() & Qt.WindowStaysOnTopHint) == on
        for w in (env.ctl._input_panel, env.ctl._dialogue, env.ctl._perm_panel):
            assert w.windowFlags() & Qt.WindowStaysOnTopHint


@pytest.mark.parametrize("event,expected", [("plan_ready", 1), ("stop", 1), ("working", 0),
    ("tool_done", 0), ("notification", 0), ("tool_error", 0), ("prompt", 0)])
def test_only_requested_event_reminders_raise_once_even_muted(env, monkeypatch, event, expected):
    calls = []
    env.ctl.set_always_on_top(False)
    env.ctl.set_muted(True)
    monkeypatch.setattr(env.ctl, "_bring_forward", lambda: calls.append(True))
    env.ctl.handle_event(event)
    assert len(calls) == expected and not env.data.always_on_top


def test_suppressed_completion_does_not_raise(env, monkeypatch):
    calls = []
    env.ctl._end_pending.add("a")
    monkeypatch.setattr(env.ctl, "_bring_forward", lambda: calls.append(True))
    env.ctl.handle_event("stop", meta={"session": "a"})
    assert calls == []


def test_permission_only_raises_for_new_head(env, monkeypatch):
    calls = []
    monkeypatch.setattr(env.ctl, "_bring_forward", lambda: calls.append(True))
    first = env.ctl.hub.permissions.open("Bash", "one")
    env.ctl._sync_permission()
    second = env.ctl.hub.permissions.open("Read", "two")
    env.ctl._sync_permission()
    env.ctl._sync_permission()
    assert len(calls) == 1
    env.ctl._on_permission_decided(first, False)
    assert len(calls) == 2 and env.ctl._perm_panel.request_id == second


def test_checkpoint_raises_once_after_badge_is_shown(env, monkeypatch):
    env.win.show()
    env.ctl.set_muted(True)
    calls = []
    monkeypatch.setattr(env.ctl, "_bring_forward", lambda: calls.append(env.win.paused_badge_shown))
    env.ctl.stop_work()
    assert not calls
    env.ctl.hub.wait_gate(0)
    env.ctl._sync_pause()
    env.ctl._sync_pause()
    assert calls == [True]
    env.ctl.resume_work(quiet=True)
    env.ctl.stop_work()
    env.ctl.hub.wait_gate(0)
    env.ctl._sync_pause()
    assert calls == [True, True]
    env.ctl.resume_work(quiet=True)


def test_raise_order_keeps_dialogs_above_pet_and_effects(env, monkeypatch):
    import shion.controller as controller
    env.ctl.open_bad_feedback()
    env.ctl.hub.permissions.open("Bash", "echo ok")
    env.ctl._sync_permission()
    calls = []
    monkeypatch.setattr(controller, "raise_without_activation", calls.append)
    env.ctl._bring_forward()
    assert calls[0] is env.win
    assert calls[-2:] == [env.ctl._input_panel, env.ctl._perm_panel]


@pytest.mark.parametrize("avail", [(0, 0, 1920, 1080), (-1920, -80, 1920, 1080),
                                  (1920, 200, 1280, 720)])
@pytest.mark.parametrize("edge", ["left", "right", "center", "top", "bottom"])
def test_dialogs_fit_current_monitor_and_avoid_body(avail, edge):
    ax, ay, aw, ah = avail
    x, y = ax + aw // 2, ay + ah // 2
    if edge == "left": x = ax
    if edge == "right": x = ax + aw - 175
    if edge == "top": y = ay
    if edge == "bottom": y = ay + ah - 200
    body = (x, y, 175, 200)
    pos = place_dialog(body, (400, 500), avail)
    rect = QRect(*pos, 400, 500)
    assert QRect(*avail).contains(rect) and not rect.intersects(QRect(*body))


def test_dialog_uses_top_when_neither_side_fits():
    body = (270, 500, 175, 200)
    x, y = place_dialog(body, (400, 250), (0, 0, 720, 800))
    assert y + 250 <= body[1] and x >= 0


def test_real_panels_and_expansion_avoid_body_and_stay_on_current_screen(env):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    env.win.move(avail.right() - env.win.width(), avail.bottom() - env.win.height())
    body = env.win.body_rect()
    env.ctl.open_bad_feedback()
    env.ctl.open_dialogue()
    env.ctl.hub.permissions.open("Bash", "long\n" * 40)
    env.ctl._sync_permission()
    panel = env.ctl._perm_panel
    panel._toggle_expanded()
    for w in (env.ctl._input_panel, env.ctl._dialogue, panel):
        assert avail.contains(w.frameGeometry())
        assert not w.frameGeometry().intersects(QRect(*body))


def test_about_uses_version_and_is_topmost_beside_pet(env):
    assert __version__ == "0.4.1"
    env.win.place_default()
    checked = []
    def inspect():
        box = env.ctl._about
        try:
            checked.append((box.text(), box.windowFlags(), box.frameGeometry()))
        finally:
            box.accept()
    QTimer.singleShot(20, inspect)
    env.ctl.show_about()
    text, flags, rect = checked[0]
    assert __version__ in text and flags & Qt.WindowStaysOnTopHint
    assert not rect.intersects(QRect(*env.win.body_rect()))
    assert QGuiApplication.primaryScreen().availableGeometry().contains(rect)


@pytest.mark.parametrize("kind", ["input", "permission", "dialogue", "snacks", "about"])
def test_scene_snapshot_contains_pet_and_panel(qapp, tmp_path, kind):
    from shion.app import snapshot_panel
    out = tmp_path / f"{kind}.png"
    assert snapshot_panel(str(out), kind, with_pet=True) == 0
    img = QImage(str(out))
    assert not img.isNull() and img.width() >= 400 and img.height() >= 200


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_flags_z_order_and_foreground_survive_toggle_and_reminder(env):
    if QGuiApplication.platformName() != "windows":
        pytest.skip("requires native Windows platform")
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    cover = QWidget(None, Qt.Tool | Qt.WindowDoesNotAcceptFocus)
    cover.setAttribute(Qt.WA_ShowWithoutActivating)
    bubble = env.ctl.bubble = BubbleWindow(autostart=False)
    try:
        foreground = user32.GetForegroundWindow()
        # 无有效前台窗口（例如锁屏）时，比对 0 只能证明句柄未变化，
        # 不能作为真实键盘焦点已验收的证据；此限制必须写入验收记录。
        env.win.show()
        env.win.set_paused_badge(True)
        bubble.follow(env.win.body_rect())
        bubble.say("test")
        env.overlay.burst(env.win.head_anchor())
        cover.resize(500, 500)
        cover.show()
        QApplication.processEvents()
        geometry, mask = env.win.geometry(), env.win.mask()
        for on in (False, True, False):
            env.ctl.set_always_on_top(on)
            QApplication.processEvents()
            for w in (env.win, bubble, env.overlay, env.win._pause_badge):
                assert bool(user32.GetWindowLongW(int(w.winId()), -20) & 8) == on
            assert env.win.geometry() == geometry and env.win.mask() == mask
            assert user32.GetForegroundWindow() == foreground
        def above(first, second):
            hwnd = user32.GetWindow(int(first.winId()), 2)  # GW_HWNDNEXT
            while hwnd:
                if hwnd == int(second.winId()):
                    return True
                hwnd = user32.GetWindow(hwnd, 2)
            return False
        raise_without_activation(cover)
        assert above(cover, env.win)  # 普通窗口能盖住诗音
        env.ctl._bring_forward()
        assert above(env.win, cover)
        assert all(above(w, cover) for w in (bubble, env.overlay, env.win._pause_badge))
        assert user32.GetForegroundWindow() == foreground
        assert not user32.GetWindowLongW(int(env.win.winId()), -20) & 8
        env.ctl.open_dialogue()
        env.ctl._bring_forward()
        assert above(env.ctl._dialogue, env.win)
        assert user32.GetForegroundWindow() == foreground
        about_styles = []
        def inspect_about():
            box = env.ctl._about
            try:
                for on in (True, False, True, False):
                    env.ctl.set_always_on_top(on)
                    about_styles.append(bool(user32.GetWindowLongW(int(box.winId()), -20) & 8))
            finally:
                box.accept()
        QTimer.singleShot(20, inspect_about)
        env.ctl.show_about()
        assert about_styles == [True] * 4
    finally:
        cover.close()
        bubble.close()
        env.ctl.bubble = None
