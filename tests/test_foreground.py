"""前台跟随：假的 Win32/Z 序 + Qt 事件，不切换用户的真实前台。"""
import ctypes
import sys

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from shion import foreground as F
from tests.test_controller import Env, qapp


class Window:
    def __init__(self, hwnd, visible=True):
        self.hwnd, self.visible = hwnd, visible
        self.id_reads = 0

    def isVisible(self):
        return self.visible

    def winId(self):
        self.id_reads += 1
        return self.hwnd


class Api:
    def __init__(self):
        self.order = [800, 70, 11, 300, 90, 10, 12]
        self.current = 300
        self.pids = {300: 400, 301: 401, 90: 500}
        self.images = {400: r"C:\Program Files\WindowsApps\Claude_1\app\Claude.exe",
                       401: r"D:\another\CLAUDE.EXE", 500: r"C:\other.exe"}
        self.topmosts = {800}
        self.invalid, self.hidden, self.minimized = set(), set(), set()
        self.calls = []
        self.registration = 123
        self.unregistration = True
        self.position_ok = True

    def callback(self, fn):
        self.calls.append(("callback",))
        return fn

    def register(self, callback, event=F.EVENT_SYSTEM_FOREGROUND):
        self.calls.append(("register", callback, event))
        return self.registration + (event == F.EVENT_SYSTEM_MINIMIZEEND) if self.registration else 0

    def unregister(self, hook):
        self.calls.append(("unregister", hook))
        return self.unregistration

    def foreground(self):
        self.calls.append(("foreground",))
        return self.current

    def usable(self, hwnd):
        return (hwnd in self.order and hwnd not in self.invalid
                and hwnd not in self.hidden and hwnd not in self.minimized)

    def pid(self, hwnd):
        return self.pids.get(hwnd, 0)

    def show_without_activation(self, hwnd):
        self.calls.append(("show_without_activation", hwnd))
        if hwnd in self.invalid:
            return False
        self.hidden.discard(hwnd)
        self.minimized.discard(hwnd)
        return self.usable(hwnd)

    def image(self, pid):
        self.calls.append(("image", pid))
        return self.images.get(pid, "")

    def previous(self, hwnd):
        self.calls.append(("previous", hwnd))
        index = self.order.index(hwnd)
        return self.order[index - 1] if index else 0

    def topmost(self, hwnd):
        return hwnd in self.topmosts

    def position(self, hwnd, after):
        self.calls.append(("position", hwnd, after))
        if not self.position_ok:
            return False
        self.order.remove(hwnd)
        if after:
            index = self.order.index(after) + 1
        else:  # HWND_TOP 不越过 topmost 区，也不把窗口变成 topmost
            index = 0
            while index < len(self.order) and self.order[index] in self.topmosts:
                index += 1
        self.order.insert(index, hwnd)
        return True

    @property
    def positions(self):
        return [c[1:] for c in self.calls if c[0] == "position"]


@pytest.fixture
def follower(qapp, monkeypatch):
    monkeypatch.setattr(F, "_native_windows", lambda: True)
    api = Api()
    windows = [Window(10), Window(11), Window(12)]
    f = F.ForegroundFollower(lambda: windows, api_factory=lambda: api)
    yield f, api, windows
    api.unregistration = True
    f.stop()


def sync(f):
    f._timer.stop()
    f._sync()


def event(f, hwnd=300, kind=F.EVENT_SYSTEM_FOREGROUND):
    f._on_event(123, kind, hwnd, 0, 0, 0, 0)


def test_initial_check_and_exact_group_above_claude_preserves_other_order(follower):
    f, api, windows = follower
    f.set_enabled(True)
    assert f._timer.isActive()
    sync(f)
    assert api.order == [800, 70, 12, 11, 10, 300, 90]
    assert api.positions == [(12, 70), (11, 12), (10, 11)]
    assert api.topmosts == {800}
    sync(f)
    assert api.order == [800, 70, 12, 11, 10, 300, 90]


@pytest.mark.parametrize("order", [[800, 300, 10, 11, 12], [300, 10, 11, 12]])
def test_topmost_or_missing_neighbour_uses_hwnd_top(follower, order):
    f, api, _ = follower
    api.order = order
    f.set_enabled(True)
    sync(f)
    assert api.positions == [(12, 0), (11, 12), (10, 11)]
    assert api.order[-4:] == [12, 11, 10, 300]
    assert api.topmosts == {800}


def test_every_attachment_hidden_window_and_duplicate(follower):
    f, api, windows = follower
    # 本体、气泡、摸头/升级爱心、碎屑、暂停标签、FPS、睡眠 Z
    windows[:] = [Window(n) for n in range(10, 17)]
    hidden = Window(17, False)
    windows.extend([None, hidden, windows[0]])
    api.order = [300] + list(range(10, 18))
    f.set_enabled(True)
    sync(f)
    assert [h for h, _ in api.positions] == list(range(16, 9, -1))
    assert api.order == list(range(16, 9, -1)) + [300, 17]
    assert hidden.id_reads == 0


@pytest.mark.parametrize("target", [0, 90, 999])
def test_other_program_null_and_destroyed_window_do_nothing(follower, target):
    f, api, _ = follower
    api.current = target
    before = api.order[:]
    f.set_enabled(True)
    sync(f)
    assert api.order == before and not api.positions


@pytest.mark.parametrize("reason", ["invalid", "hidden", "minimized", "no_pid", "no_image"])
def test_unusable_claude_and_query_failures_do_nothing(follower, reason):
    f, api, _ = follower
    if reason in ("invalid", "hidden", "minimized"):
        getattr(api, reason).add(300)
    elif reason == "no_pid":
        api.pids.clear()
    else:
        api.images.clear()
    f.set_enabled(True)
    sync(f)
    assert not api.positions


def test_multiple_claude_pids_titles_and_case_independent(follower):
    f, api, _ = follower
    f.set_enabled(True)
    sync(f)
    api.order.insert(0, 301)
    api.current = 301
    event(f, 301)
    sync(f)
    assert api.order[:4] == [12, 11, 10, 301]
    assert ("image", 401) in api.calls


def test_callback_is_deferred_and_burst_is_coalesced(follower, qapp):
    f, api, _ = follower
    f.set_enabled(True)
    sync(f)
    api.calls.clear()
    for _ in range(100):
        event(f)
    assert f._timer.isActive() and api.calls == []
    qapp.processEvents()
    assert api.calls.count(("image", 400)) == 1


@pytest.mark.parametrize("when", ["queued", "during_query", "during_position"])
def test_switch_to_other_program_cancels_stale_work(follower, when):
    f, api, _ = follower
    f.set_enabled(True)
    event(f)
    if when == "queued":
        api.current = 90
    elif when == "during_query":
        original = api.image
        def image(pid):
            api.current = 90
            return original(pid)
        api.image = image
    else:
        original = api.position
        def position(hwnd, after):
            result = original(hwnd, after)
            api.current = 90
            return result
        api.position = position
    sync(f)
    assert len(api.positions) == (1 if when == "during_position" else 0)


def test_pid_reused_during_query_does_nothing(follower):
    f, api, _ = follower
    def image(pid):
        api.pids[300] = 999
        return "Claude.exe"
    api.image = image
    f.set_enabled(True)
    sync(f)
    assert not api.positions


def test_late_window_and_recreated_handle_come_from_current_provider(follower):
    f, api, windows = follower
    f.set_enabled(True)
    sync(f)
    windows.append(Window(13))
    api.order.append(13)
    f.eventFilter(windows[-1], QEvent(QEvent.Show))
    assert f._timer.isActive()
    sync(f)
    assert api.order[2:7] == [13, 12, 11, 10, 300]
    windows[1].hwnd = 21
    api.order.remove(11)
    api.order.append(21)
    f.eventFilter(windows[1], QEvent(QEvent.WinIdChange))
    sync(f)
    assert api.order[2:7] == [13, 12, 21, 10, 300]


def test_real_qt_show_event_is_observed_without_activation(follower, qapp):
    f, api, windows = follower
    f.set_enabled(True)
    sync(f)
    widget = QWidget()
    widget.setAttribute(Qt.WA_ShowWithoutActivating)
    windows.append(widget)
    try:
        widget.show()
        api.order.append(int(widget.winId()))
        assert f._timer.isActive()
        qapp.processEvents()
        assert api.positions[-4][0] == int(widget.winId())
        assert widget.testAttribute(Qt.WA_ShowWithoutActivating)
    finally:
        windows.remove(widget)
        widget.close()


def test_unrelated_show_move_and_other_event_are_ignored(follower):
    f, api, windows = follower
    f.set_enabled(True)
    sync(f)
    f.eventFilter(Window(55), QEvent(QEvent.Show))
    f.eventFilter(windows[0], QEvent(QEvent.Move))
    event(f, kind=999)
    event(f, hwnd=0)
    assert not f._timer.isActive()


def test_stopping_cancels_pending_work_and_reenable_registers_once(follower):
    f, api, _ = follower
    f.set_enabled(True)
    callback = f._callback
    f.set_enabled(True)
    f.set_enabled(False)
    f.stop()
    callback(123, F.EVENT_SYSTEM_FOREGROUND, 300, 0, 0, 0, 0)
    sync(f)
    assert not f._timer.isActive() and not api.positions
    assert f._hook is None and f._callback is None
    assert sum(c[0] == "register" for c in api.calls) == 2
    assert api.calls.count(("unregister", 123)) == 1
    assert api.calls.count(("unregister", 124)) == 1
    assert all(not t.isActive() for t in f._retry_timers)
    f.set_enabled(True)
    sync(f)
    assert sum(c[0] == "register" for c in api.calls) == 4
    assert api.positions


@pytest.mark.parametrize("failure", ["return", "exception"])
def test_registration_failure_is_nonfatal(follower, failure, caplog):
    f, api, _ = follower
    api.registration = 0
    if failure == "exception":
        def fail(callback, event=F.EVENT_SYSTEM_FOREGROUND):
            raise OSError("unavailable")
        api.register = fail
    f.set_enabled(True)
    assert not f._enabled and not f._timer.isActive() and f._callback is None
    f.stop()
    assert not api.positions and caplog.records


@pytest.mark.parametrize("failure", ["return", "exception"])
def test_unhook_failure_retains_callback_and_retries(follower, failure, caplog):
    f, api, _ = follower
    f.set_enabled(True)
    callback = f._callback
    api.unregistration = False
    original = api.unregister
    if failure == "exception":
        def fail(hook):
            raise OSError("unavailable")
        api.unregister = fail
    f.stop()
    assert f._callback is callback and f._hook == 123 and not f._enabled
    event(f)
    assert not f._timer.isActive() and caplog.records
    api.unregister = original
    api.unregistration = True
    f.stop()
    assert f._hook is f._callback is None


def test_position_failure_and_exception_are_nonfatal(follower, caplog):
    f, api, _ = follower
    f.set_enabled(True)
    api.position_ok = False
    sync(f)
    assert len(api.positions) == 1
    api.calls.clear()
    def fail(pid):
        raise OSError("unavailable")
    api.image = fail
    sync(f)
    assert not api.positions and caplog.records


def test_racing_z_order_cycle_aborts_without_loop(follower):
    f, api, _ = follower
    api.previous = lambda hwnd: 11
    f.set_enabled(True)
    sync(f)
    assert not api.positions


@pytest.mark.parametrize("platform,qt", [("linux", "xcb"), ("darwin", "cocoa"),
                                       ("win32", "offscreen")])
def test_unsupported_platform_never_loads_win32(qapp, monkeypatch, platform, qt):
    monkeypatch.setattr(F.sys, "platform", platform)
    monkeypatch.setattr(F.QGuiApplication, "platformName", lambda: qt)
    def forbidden():
        pytest.fail("must not load native API")
    f = F.ForegroundFollower(lambda: (), api_factory=forbidden)
    f.set_enabled(True)
    f.stop()
    assert not f._enabled and f._callback is None


def test_application_exit_stops_hook(follower, monkeypatch):
    f, api, _ = follower
    # 只触发本对象的连接，避免向测试进程的 QApplication 广播退出。
    slots = []
    class Signal:
        def connect(self, slot):
            slots.append(slot)
    class App:
        aboutToQuit = Signal()
        def installEventFilter(self, obj):
            pass
        def removeEventFilter(self, obj):
            pass
    monkeypatch.setattr(F.QApplication, "instance", lambda: App())
    second = F.ForegroundFollower(lambda: (), api_factory=lambda: api)
    second.set_enabled(True)
    slots[0]()
    assert not second._enabled and second._hook is None
    second.stop()


def test_controller_switch_lifecycle_and_current_full_group(qapp, tmp_path, monkeypatch):
    import shion.controller as C
    instances = []
    class Follower:
        def __init__(self, windows, parent):
            self.windows, self.parent = windows, parent
            self.calls = []
            instances.append(self)
        def stop(self):
            self.calls.append("stop")
        def set_enabled(self, enabled):
            self.calls.append(enabled)
    monkeypatch.setattr(C, "ForegroundFollower", Follower)
    e = Env(tmp_path)
    try:
        spy = instances[0]
        assert spy.calls[-1] is False
        assert spy.parent is e.ctl
        assert spy.windows() == e.ctl._pet_windows()
        e.ctl.set_always_on_top(False)
        assert spy.calls[-1] is True
        e.win.set_paused_badge(True)
        e.win.set_state("sleep", animate=False)
        assert e.win._pause_badge in spy.windows()
        assert e.win._sleep_z in spy.windows()
        e.ctl.set_always_on_top(True)
        assert spy.calls[-1] is False
        e.ctl.quit()
        assert spy.calls[-1] == "stop"
    finally:
        e.close()
    assert spy.calls[-1] == "stop"


@pytest.mark.skipif(sys.platform != "win32", reason="ctypes WINFUNCTYPE requires Windows")
def test_native_api_signatures_registration_flags_and_noactivate_position(monkeypatch):
    class Fn:
        def __init__(self, result=1):
            self.calls, self.result = [], result
        def __call__(self, *args):
            self.calls.append(args)
            return self.result
    class DLL:
        pass
    dll = DLL()
    for name in ("SetWinEventHook", "UnhookWinEvent", "GetForegroundWindow",
                 "GetWindowThreadProcessId", "IsWindow", "IsWindowVisible", "IsIconic",
                 "GetWindow", "GetWindowLongW", "SetWindowPos", "ShowWindow"):
        setattr(dll, name, Fn())
    monkeypatch.setattr(F.ctypes, "WinDLL", lambda *a, **kw: dll)
    api = F._Win32ForegroundApi()
    callback = api.callback(lambda *args: None)
    assert api.register(callback) == 1
    assert dll.SetWinEventHook.calls == [(3, 3, None, callback, 0, 0, 0)]
    api.register(callback, F.EVENT_SYSTEM_MINIMIZEEND)
    assert dll.SetWinEventHook.calls[-1] == (23, 23, None, callback, 0, 0, 0)
    dll.IsIconic.result = 0
    dll.ShowWindow.result = 0  # 此前不可见不等于本次恢复失败
    assert api.show_without_activation(2**40 + 1)
    assert dll.ShowWindow.calls == [(2**40 + 1, 4)]
    api.position(2**40 + 1, 2**40 + 2)
    assert dll.SetWindowPos.calls == [(2**40 + 1, 2**40 + 2, 0, 0, 0, 0, 0x213)]
    assert dll.SetWindowPos.argtypes[:2] == [F.wintypes.HWND, F.wintypes.HWND]
    assert dll.SetWinEventHook.restype == F.wintypes.HANDLE
    api.unregister(1)
    assert dll.UnhookWinEvent.calls == [(1,)]
    assert not hasattr(dll, "SetForegroundWindow")
    assert not hasattr(dll, "SetWindowLongPtrW")


@pytest.mark.parametrize("restore_after", [50, 250])
def test_foreground_before_restore_gets_two_finite_rechecks(follower, qapp, restore_after):
    f, api, _ = follower
    api.minimized.add(300)
    f.set_enabled(True)
    qapp.processEvents()
    assert not api.positions
    assert [t.interval() for t in f._retry_timers] == [150, 500]
    assert all(t.isActive() for t in f._retry_timers)
    QTest.qWait(restore_after)
    api.minimized.clear()  # FOREGROUND 比恢复完成早；也不再发任何系统事件
    QTest.qWait(600 - restore_after)
    assert api.order[2:6] == [12, 11, 10, 300]
    assert api.calls.count(("image", 400)) == 3  # 立即、150ms、500ms，无轮询
    calls = len(api.calls)
    QTest.qWait(180)
    assert len(api.calls) == calls
    assert all(not t.isActive() for t in f._retry_timers)


def test_minimizeend_rechecks_current_foreground_and_bursts_keep_deadlines(follower):
    f, api, _ = follower
    f.set_enabled(True)
    sync(f)
    assert [c[2] for c in api.calls if c[0] == "register"] == [3, 23]
    ids = [t.timerId() for t in f._retry_timers]
    api.calls.clear()
    for _ in range(100):
        event(f, kind=F.EVENT_SYSTEM_MINIMIZEEND)
    assert api.calls == []  # 回调仍不查进程、不排 Z 序
    sync(f)
    assert [t.timerId() for t in f._retry_timers] == ids
    assert api.calls.count(("image", 400)) == 1
    api.current = 90
    event(f, kind=F.EVENT_SYSTEM_MINIMIZEEND)
    sync(f)
    assert all(not t.isActive() for t in f._retry_timers)


@pytest.mark.parametrize("state", ["hidden", "minimized"])
def test_system_hidden_pet_is_restored_but_explicitly_hidden_attachment_is_not(follower, state):
    f, api, windows = follower
    getattr(api, state).update([10, 11, 12])
    windows[2].visible = False  # 程序主动收起的特效不能复活
    f.set_enabled(True)
    sync(f)
    assert [c[1] for c in api.calls if c[0] == "show_without_activation"] == [10, 11]
    assert api.positions == [(11, 70), (10, 11)]
    assert 12 in getattr(api, state)
    assert api.current == 300 and api.topmosts == {800}


@pytest.mark.parametrize("failure", ["return", "exception"])
def test_second_hook_failure_cleans_first_and_can_retry(follower, failure):
    f, api, _ = follower
    original = api.register
    def register(callback, event=F.EVENT_SYSTEM_FOREGROUND):
        if event == F.EVENT_SYSTEM_MINIMIZEEND:
            if failure == "exception":
                raise OSError("restore hook unavailable")
            return 0
        return original(callback, event)
    api.register = register
    f.set_enabled(True)
    assert not f._enabled and f._hook is f._restore_hook is f._callback is None
    assert ("unregister", 123) in api.calls
    api.register = original
    f.set_enabled(True)
    assert f._enabled and f._restore_hook == 124


def test_failed_cleanup_of_second_hook_keeps_callback_until_retry(follower):
    f, api, _ = follower
    f.set_enabled(True)
    callback = f._callback
    original = api.unregister
    api.unregister = lambda hook: False if hook == 124 else original(hook)
    f.stop()
    assert f._hook is None and f._restore_hook == 124 and f._callback is callback
    f.set_enabled(True)
    assert not f._enabled  # 仍注销失败，不注册新 hook
    api.unregister = original
    f.set_enabled(True)
    assert f._enabled and f._hook == 123 and f._restore_hook == 124


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_native_controlled_group_z_order_without_changing_real_foreground(qapp):
    if not F._native_windows():
        pytest.skip("requires native Windows Qt")
    from shion.bubble import BubbleWindow
    from shion.effects import CrumbOverlay, HeartOverlay
    from shion.pet_window import PetWindow
    from shion.windowing import set_topmost

    # 目标窗口/进程识别用替身；真实 Win32 只操作本测试创建的窗口。
    target = QWidget(None, Qt.Tool | Qt.WindowDoesNotAcceptFocus)
    target.setAttribute(Qt.WA_ShowWithoutActivating)
    pet = PetWindow(autostart=False, debug=True)
    bubble = BubbleWindow(autostart=False)
    heart = HeartOverlay(autostart=False)
    crumbs = CrumbOverlay(autostart=False)
    pet.set_state("sleep", animate=False)
    pet.set_paused_badge(True)
    windows = [pet, bubble, heart, crumbs, pet._pause_badge, pet._fps_overlay, pet._sleep_z]
    api = F._Win32ForegroundApi()
    before = api.foreground()

    class ControlledApi(F._Win32ForegroundApi):
        def foreground(self):
            return int(target.winId())
        def image(self, pid):
            return "Claude.exe"

    f = F.ForegroundFollower(lambda: windows, api_factory=ControlledApi)
    try:
        for window in [target, *windows]:
            set_topmost(window, False)
            window.show()
        qapp.processEvents()
        f.set_enabled(True)
        qapp.processEvents()
        ids = [int(w.winId()) for w in reversed(windows)] + [int(target.winId())]
        assert all(api.previous(below) == above for above, below in zip(ids, ids[1:]))
        assert all(not api.topmost(int(w.winId())) for w in windows)
        # 返回 0 时无法证明焦点，仍验证真实 Z 序；真实焦点留待用户验收。
        if before:
            assert api.foreground() == before
    finally:
        f.stop()
        for window in reversed([target, *windows]):
            window.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
@pytest.mark.parametrize("shell_show_state", [0, 6])  # SW_HIDE / SW_MINIMIZE
def test_native_system_hidden_pet_restores_geometry_and_mask_without_activation(qapp, shell_show_state):
    if not F._native_windows():
        pytest.skip("requires native Windows Qt")
    from shion.pet_window import PetWindow
    from shion.windowing import set_topmost

    target = QWidget(None, Qt.Tool | Qt.WindowDoesNotAcceptFocus)
    target.setAttribute(Qt.WA_ShowWithoutActivating)
    pet = PetWindow(autostart=False)
    api = F._Win32ForegroundApi()
    class ControlledApi(F._Win32ForegroundApi):
        def foreground(self):
            return int(target.winId())
        def image(self, pid):
            return "Claude.exe"
    f = F.ForegroundFollower(lambda: [pet], api_factory=ControlledApi)
    try:
        for window in (target, pet):
            set_topmost(window, False)
            window.show()
        qapp.processEvents()
        geometry, mask = pet.geometry(), pet.mask()
        before = api.foreground()
        api.user32.ShowWindow(int(pet.winId()), shell_show_state)
        qapp.processEvents()
        assert pet.isVisible()  # 系统隐藏不是程序调用 hide()
        assert not api.usable(int(pet.winId()))
        f.set_enabled(True)
        qapp.processEvents()
        assert api.usable(int(pet.winId()))
        assert pet.geometry() == geometry and pet.mask() == mask
        assert not api.topmost(int(pet.winId()))
        assert api.previous(int(target.winId())) == int(pet.winId())
        if before:
            assert api.foreground() == before
    finally:
        f.stop()
        pet.close()
        target.close()
