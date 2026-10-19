"""窗口层测试：离屏运行（QT_QPA_PLATFORM=offscreen），不需要真实显示器。"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from shion.app import SingleInstance
from shion.pet_window import (
    DEFAULT_HEIGHT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, STATES,
    PetWindow, landing_geometry,
)

BODY = QPoint(MARGIN_X + 60, MARGIN_TOP + 120)  # 精灵身体中间


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = PetWindow()
    yield w
    w.close()


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def fwin(qapp):
    """假时钟、不开定时器的窗口：手动 advance_to，不用真的等。"""
    clk = FakeClock()
    w = PetWindow(clock=clk, autostart=False)
    w.clk = clk
    yield w
    w.close()


def at(w, seconds):
    w.clk.t += seconds
    w.advance_to(w.clk.t)


def alpha_of(w):
    img = w.render_frame().convertToFormat(QImage.Format_RGBA8888)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return arr[:, : img.width(), 3].copy()  # 复制：img 一出函数就会释放


def test_landing_geometry_clamps_x_and_sets_floor():
    avail = QRect(0, 0, 1920, 1040)  # 底边 y=1039
    assert landing_geometry(avail, 120, 240, 500) == (500, 800)
    assert landing_geometry(avail, 120, 240, -50)[0] == 0
    assert landing_geometry(avail, 120, 240, 5000)[0] == 1920 - 120
    # 留边：精灵本体不出屏，画布可以伸出去
    assert landing_geometry(avail, 248, 254, -500, 64, 6) == (-64, 1040 - 254 + 6)
    assert landing_geometry(avail, 248, 254, 5000, 64, 6)[0] == 1920 - 248 + 64


@pytest.mark.parametrize("name", STATES)
def test_all_sprites_load_at_default_size(win, name):
    win.set_state(name)
    w, h = win.sprite_size
    assert h == DEFAULT_HEIGHT
    assert w == DEFAULT_HEIGHT // 2  # 256x512 等比例
    assert win.width() == w + 2 * MARGIN_X
    assert win.height() == h + MARGIN_TOP + MARGIN_BOTTOM
    assert win.sprite_name == name


def test_unknown_sprite_rejected(win):
    with pytest.raises(ValueError):
        win.set_state("nope")


def test_transparent_corners_are_masked_out(win):
    """透明像素不在 mask 里 = 点击穿透。"""
    m = win.mask()
    assert not m.isEmpty()
    assert not m.contains(QPoint(0, 0))
    assert not m.contains(QPoint(win.width() - 1, 0))
    assert not m.contains(QPoint(5, win.height() // 2))  # 留边区域
    assert m.contains(BODY)


def test_default_position_is_bottom_right_feet_on_floor(win):
    win.place_default()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert win.y() + win.height() - MARGIN_BOTTOM == avail.bottom() + 1
    assert win.x() + MARGIN_X + win.sprite_size[0] <= avail.right() + 1


# ---- 动画：锚点和遮罩 ----
def feet_metrics(a):
    """不透明像素的最低行，以及整体包围盒的水平中点。"""
    rows = np.where(a.max(axis=1) > 20)[0]
    cols = np.where(a.max(axis=0) > 20)[0]
    return rows.max(), (cols.min() + cols.max()) / 2


def feet_x(a):
    """最低 8 行不透明像素的平均横坐标，即脚的位置。"""
    rows = np.where(a.max(axis=1) > 20)[0]
    sub = a[rows.max() - 8 : rows.max() + 1] > 20
    return np.where(sub)[1].mean()


def test_anchor_idle_breath_does_not_float(fwin):
    fwin.set_state("happy")  # happy 有晃动，先用无晃动的 neglect2 做基准
    fwin.set_state("neglect1")  # 只有呼吸
    base = feet_metrics(alpha_of(fwin))
    for _ in range(30):
        at(fwin, 0.1)  # 走过整整一个 3 秒呼吸周期
        low, mid = feet_metrics(alpha_of(fwin))
        assert abs(low - base[0]) <= 1
        assert abs(mid - base[1]) <= 1.5


def test_breath_actually_changes_frame(fwin):
    fwin.set_state("neglect1")
    at(fwin, 1.5)
    assert fwin.frame.sy == pytest.approx(1.012, abs=1e-3)


def test_anchor_squash_keeps_feet_in_place(fwin):
    fwin.set_state("neglect2")  # 没有呼吸、没有晃动
    base = feet_metrics(alpha_of(fwin))
    fwin._animator.squash(fwin.clk.t, "land")
    seen_squash = False
    for _ in range(20):
        at(fwin, 0.0125)
        if fwin.frame.sy < 0.95:
            seen_squash = True
        low, mid = feet_metrics(alpha_of(fwin))
        assert abs(low - base[0]) <= 1
        assert abs(mid - base[1]) <= 1.5
    assert seen_squash


def test_anchor_dizzy_sway_not_clipped_and_stays_put(fwin):
    fwin.set_state("dizzy")
    a0 = alpha_of(fwin)
    base = feet_metrics(a0)
    base_x = feet_x(a0)
    max_angle = 0.0
    for _ in range(36):
        at(fwin, 0.025)
        a = alpha_of(fwin)
        low, mid = feet_metrics(a)
        max_angle = max(max_angle, abs(fwin.frame.angle))
        assert low < fwin.height() - 1  # 画布底边没有被裁
        assert abs(low - base[0]) <= 4  # 一只脚下沉、一只上抬
        assert abs(feet_x(a) - base_x) <= 3  # 脚的水平位置不滑（头会晃，所以只看脚）
    assert max_angle > 4.9


@pytest.mark.parametrize(
    "state,secs,squash",
    [("idle", 1.5, None), ("dizzy", 0.225, None), ("neglect2", 0.1, "land"),
     ("happy", 0.15, "click"), ("drag", 0.0, None)],
)
def test_mask_is_superset_of_drawn_pixels(fwin, state, secs, squash):
    fwin.set_state(state)
    if squash:
        fwin._animator.squash(fwin.clk.t, squash)
    at(fwin, secs)
    a = alpha_of(fwin)
    m = fwin.mask()
    ys, xs = np.where(a > 64)  # 肉眼可见的像素；alpha 很低的零星边缘不要求
    assert len(ys) > 1000
    missing = [(x, y) for x, y in zip(xs.tolist(), ys.tolist()) if not m.contains(QPoint(x, y))]
    assert not missing, missing[:5]


def test_mask_superset_while_tilted(fwin):
    fwin.set_state("drag")
    fwin._animator.set_drag(True)
    for _ in range(40):
        fwin._animator.feed_velocity(2000, fwin.clk.t)
        at(fwin, 1 / 60)
    assert abs(fwin.frame.angle) > 8
    a = alpha_of(fwin)
    m = fwin.mask()
    ys, xs = np.where(a > 64)  # 肉眼可见的像素；alpha 很低的零星边缘不要求
    assert all(m.contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
    # 头部没被画布裁掉：最上面一行不透明像素在画布内部
    assert ys.min() > 0


# ---- 鼠标 ----
def test_small_movement_is_not_a_drag(win):
    win.place_default()
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, BODY)
    QTest.mouseMove(win, BODY + QPoint(3, 0))
    assert not win.is_dragging
    assert win.sprite_name == "idle"
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, BODY + QPoint(3, 0))
    assert not win.is_falling


def test_click_triggers_squash(fwin):
    fwin.set_state("neglect2")
    QTest.mousePress(fwin, Qt.LeftButton, Qt.NoModifier, BODY)
    QTest.mouseRelease(fwin, Qt.LeftButton, Qt.NoModifier, BODY)
    at(fwin, 0.05)
    assert fwin.frame.sy < 1.0 and fwin.frame.sx > 1.0
    at(fwin, 0.5)
    assert fwin.frame.sy == 1.0


def test_drag_switches_sprite_and_release_falls_to_floor(win, qapp):
    win.place_default()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    floor_y = avail.bottom() + 1 - win.height() + MARGIN_BOTTOM
    win.show()
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, BODY)
    # 向上拖 300px，必须先越过 6px 阈值
    QTest.mouseMove(win, BODY + QPoint(0, -300))
    assert win.is_dragging
    assert win.sprite_name == "drag"
    assert win.y() < floor_y - 100

    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, BODY + QPoint(0, -300))
    assert win.is_falling
    deadline = time.monotonic() + 3
    while win.is_falling and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not win.is_falling
    assert win.y() == floor_y  # 脚底贴底，不越界
    assert win.sprite_name == "idle"


def test_landing_triggers_squash_then_settles(fwin):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    fwin.move(avail.left() + 50, avail.top())
    fwin.set_state("drag")
    fwin.start_fall()
    for _ in range(200):
        if not fwin.is_falling:
            break
        at(fwin, 1 / 60)
    assert not fwin.is_falling
    assert fwin.sprite_name == "idle"
    at(fwin, 0.05)
    assert fwin.frame.sy < 1.0  # 落地压扁
    at(fwin, 0.5)
    assert fwin.frame.sy == pytest.approx(1.0, abs=0.013)  # 只剩呼吸


def test_tilt_while_dragging_then_resets_after_release(fwin):
    fwin.place_default()
    QTest.mousePress(fwin, Qt.LeftButton, Qt.NoModifier, BODY)
    pos = BODY
    for _ in range(30):  # 快速向右拖
        pos = pos + QPoint(12, 0)
        QTest.mouseMove(fwin, pos)
        at(fwin, 1 / 60)
    assert fwin.is_dragging
    assert fwin.frame.angle < -1.0
    QTest.mouseRelease(fwin, Qt.LeftButton, Qt.NoModifier, pos)
    for _ in range(300):
        at(fwin, 1 / 60)
        if not fwin.is_falling and fwin.frame.angle == 0.0:
            break
    assert fwin.frame.angle == 0.0


def test_release_below_floor_pulls_back_onto_screen(win, qapp):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.left() + 50, avail.bottom() + 200)  # 拖到屏幕外
    win.start_fall()
    QTest.qWait(50)
    assert win.y() + win.height() - MARGIN_BOTTOM <= avail.bottom() + 1


def test_press_during_fall_stops_it(win, qapp):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.left() + 50, avail.top())
    win.start_fall()
    assert win.is_falling
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, BODY)
    assert not win.is_falling
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, BODY)


def test_single_instance_second_acquire_fails(qapp):
    name = f"ShionTest-{os.getpid()}-{time.monotonic_ns()}"
    a, b = SingleInstance(name), SingleInstance(name)
    try:
        assert a.acquire() is True
        assert b.acquire() is False
    finally:
        a.release()
        b.release()
    c = SingleInstance(name)  # 第一个退出后可以重新获取
    try:
        assert c.acquire() is True
    finally:
        c.release()


def test_snapshot_cli_writes_transparent_png_and_at_changes_frame(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    outs = []
    for name, extra in [("a", []), ("b", ["--at", "0.225"])]:
        out = tmp_path / f"{name}.png"
        r = subprocess.run(
            [sys.executable, "-m", "shion", "--snapshot", str(out), "--state", "dizzy", *extra],
            cwd=root, capture_output=True, timeout=60,
        )
        assert r.returncode == 0, r.stderr
        outs.append(out)
    from PIL import Image

    a, b = Image.open(outs[0]), Image.open(outs[1])
    w = DEFAULT_HEIGHT // 2 + 2 * MARGIN_X
    h = DEFAULT_HEIGHT + MARGIN_TOP + MARGIN_BOTTOM
    assert a.size == (w, h)
    assert a.mode == "RGBA"
    assert a.getpixel((0, 0))[3] == 0
    assert list(a.getdata()) != list(b.getdata())  # 晃到最大角度和 0 秒不同
