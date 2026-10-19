"""窗口层测试：离屏运行（QT_QPA_PLATFORM=offscreen），不需要真实显示器。"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from shion.app import SingleInstance
from shion.pet_window import DEFAULT_HEIGHT, STATES, PetWindow, landing_geometry


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = PetWindow()
    yield w
    w.close()


def test_landing_geometry_clamps_x_and_sets_floor():
    avail = QRect(0, 0, 1920, 1040)  # 底边 y=1039
    assert landing_geometry(avail, 120, 240, 500) == (500, 800)
    assert landing_geometry(avail, 120, 240, -50)[0] == 0
    assert landing_geometry(avail, 120, 240, 5000)[0] == 1920 - 120


@pytest.mark.parametrize("name", STATES)
def test_all_sprites_load_at_default_size(win, name):
    win.set_sprite(name)
    assert win.height() == DEFAULT_HEIGHT
    assert win.width() == DEFAULT_HEIGHT // 2  # 256x512 等比例
    assert win.sprite_name == name


def test_unknown_sprite_rejected(win):
    with pytest.raises(ValueError):
        win.set_sprite("nope")


def test_transparent_corners_are_masked_out(win):
    """透明像素不在 mask 里 = 点击穿透。"""
    m = win.mask()
    assert not m.isEmpty()
    assert not m.contains(QPoint(0, 0))
    assert not m.contains(QPoint(win.width() - 1, 0))
    assert m.contains(QPoint(win.width() // 2, win.height() // 2))


def test_default_position_is_bottom_right_feet_on_floor(win):
    win.place_default()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert win.y() + win.height() == avail.bottom() + 1
    assert win.x() + win.width() <= avail.right() + 1


def _press_move_release(win, start, delta):
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(win, start + delta)
    return start + delta


def test_small_movement_is_not_a_drag(win):
    win.place_default()
    start = QPoint(60, 120)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(win, start + QPoint(3, 0))
    assert not win.is_dragging
    assert win.sprite_name == "idle"
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, start + QPoint(3, 0))
    assert not win.is_falling


def test_drag_switches_sprite_and_release_falls_to_floor(win, qapp):
    win.place_default()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    floor_y = avail.bottom() + 1 - win.height()
    win.show()
    start = QPoint(60, 120)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, start)
    # 向上拖 300px，必须先越过 6px 阈值
    QTest.mouseMove(win, start + QPoint(0, -300))
    assert win.is_dragging
    assert win.sprite_name == "drag"
    assert win.y() < floor_y - 100

    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, start + QPoint(0, -300))
    assert win.is_falling
    deadline = time.monotonic() + 3
    while win.is_falling and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not win.is_falling
    assert win.y() == floor_y  # 脚底贴底，不越界
    assert win.sprite_name == "idle"


def test_release_below_floor_pulls_back_onto_screen(win, qapp):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.left() + 50, avail.bottom() + 200)  # 拖到屏幕外
    win.start_fall()
    QTest.qWait(50)
    assert win.y() + win.height() <= avail.bottom() + 1


def test_press_during_fall_stops_it(win, qapp):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.left() + 50, avail.top())
    win.start_fall()
    assert win.is_falling
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, QPoint(60, 120))
    assert not win.is_falling
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(60, 120))


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


def test_snapshot_cli_writes_transparent_png(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    out = tmp_path / "s.png"
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "shion", "--snapshot", str(out), "--state", "happy"],
        cwd=root, capture_output=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    from PIL import Image

    im = Image.open(out)
    assert im.size == (DEFAULT_HEIGHT // 2, DEFAULT_HEIGHT)
    assert im.mode == "RGBA"
    assert im.getpixel((0, 0))[3] == 0
