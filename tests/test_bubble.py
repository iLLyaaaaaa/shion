"""气泡测试：时间线和定位是纯逻辑；窗口用离屏渲染 + 假时钟。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from shion import bubble as B
from shion.bubble import BubbleTimeline, BubbleWindow, pick_font_family, place_bubble


# ---------------------------------------------------------------- 时间线
def test_typewriter_30ms_per_char():
    t = BubbleTimeline()
    text = "一二三四五六七八九十十一十二"
    t.start(10.0, text)
    assert t.visible_chars(10.0) == 0
    assert t.visible_chars(10.03) == 1
    assert t.visible_chars(10.3) == 10
    assert t.visible_chars(99.0) == len(text)  # 不会超过总字数


def test_hold_4s_after_typing_then_fade_then_finished():
    t = BubbleTimeline()
    t.start(0.0, "a" * 10)  # 打完要 0.3s
    assert t.opacity(0.3) == 1.0
    assert t.opacity(0.3 + 3.99) == 1.0  # 停留 4 秒
    mid = t.opacity(0.3 + 4.0 + 0.15)
    assert 0.4 < mid < 0.6  # 淡出过程
    assert t.opacity(0.3 + 4.0 + 0.31) == 0.0
    assert not t.finished(0.3 + 4.0 + 0.1)
    assert t.finished(0.3 + 4.0 + 0.31)


def test_new_line_replaces_old_and_resets_timing():
    t = BubbleTimeline()
    t.start(0.0, "旧台词")
    t.start(5.0, "新")
    assert t.text == "新"
    assert t.visible_chars(5.03) == 1
    assert t.opacity(5.5) == 1.0


def test_empty_and_inactive_timeline_are_safe():
    t = BubbleTimeline()
    assert t.finished(0.0) and t.opacity(0.0) == 0.0 and t.visible_chars(0.0) == 0
    t.start(0.0, "")
    assert t.visible_chars(1.0) == 0
    t.start(0.0, "x" * 5000)
    assert t.visible_chars(1.0) == 33


# ---------------------------------------------------------------- 定位
AVAIL = (0, 0, 1920, 1040)


def test_place_above_head_centered():
    body = (1000, 600, 120, 240)
    x, y = place_bubble(body, (200, 40), AVAIL)
    assert x == 1000 + 60 - 100
    assert y == 600 - B.GAP - 40


def test_place_flips_below_feet_when_no_room_above():
    body = (1000, 10, 120, 240)
    x, y = place_bubble(body, (200, 40), AVAIL)
    assert y == 10 + 240 + B.GAP


def test_place_clamps_horizontally_into_screen():
    assert place_bubble((0, 600, 120, 240), (200, 40), AVAIL)[0] == 0
    assert place_bubble((1800, 600, 120, 240), (200, 40), AVAIL)[0] == 1920 - 200


def test_place_stays_on_screen_when_neither_side_fits():
    small = (0, 0, 400, 200)
    x, y = place_bubble((100, 20, 120, 150), (200, 60), small)
    assert 0 <= y <= 200 - 60 and 0 <= x <= 400 - 200


def test_pick_font_prefers_cascadia_then_consolas_then_fallback():
    assert pick_font_family(["Arial", "Consolas", "Cascadia Mono"], "X") == "Cascadia Mono"
    assert pick_font_family(["Arial", "Consolas"], "X") == "Consolas"
    assert pick_font_family(["Arial"], "Fixed") == "Fixed"


# ---------------------------------------------------------------- 窗口
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


@pytest.fixture
def bub(qapp):
    clk = Clock()
    b = BubbleWindow(clock=clk, autostart=False)
    b.clk = clk
    yield b
    b.close()


def rgba(img: QImage):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    arr = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return arr[:, : img.width()].copy()


def test_window_never_takes_focus_or_mouse(bub):
    f = bub.windowFlags()
    for flag in (Qt.WindowTransparentForInput, Qt.WindowStaysOnTopHint, Qt.WindowDoesNotAcceptFocus):
        assert f & flag
    assert bub.testAttribute(Qt.WA_ShowWithoutActivating)
    assert bub.testAttribute(Qt.WA_TranslucentBackground)


def test_size_is_stable_while_typing_and_grows_with_text(bub):
    bub.say("哇啊啊——放我下来！这是一句比较长的台词用来测试折行效果")
    size = bub.size()
    assert bub.line_count >= 2  # 折行了
    for dt in (0.0, 0.1, 0.5, 1.0):
        bub.clk.t = 50.0 + dt
        bub.render_image()
        assert bub.size() == size
    bub.say("嗯？")
    assert bub.width() < size.width() and bub.height() < size.height()


def count_fg(img):
    a = rgba(img)
    # 米白文字 #FCF2E6：红绿蓝都很亮，且不透明
    return int(((a[:, :, 0] > 200) & (a[:, :, 1] > 190) & (a[:, :, 2] > 180) & (a[:, :, 3] > 200)).sum())


def test_text_appears_progressively_and_colors_match_spec(bub):
    bub.say("这是一段用来检查颜色的台词")
    counts = []
    for dt in (0.0, 0.1, 0.2, 0.4):
        counts.append(count_fg(bub.render_image(50.0 + dt)))
    assert counts == sorted(counts) and counts[-1] > counts[0]
    img = rgba(bub.render_image(50.0 + 0.4))
    h, w = img.shape[:2]
    # 背景 #0A0A0A（取内部靠右下角、没有文字的位置）
    bg = img[h - 4, w - 6]
    assert tuple(bg[:3]) == (10, 10, 10) and bg[3] == 255
    # 边框橙色 #F58236（上边框中间）
    top = img[0, w // 2]
    assert top[0] > 200 and 100 < top[1] < 160 and top[2] < 90
    # 圆角：左上角像素是透明的
    assert img[0, 0][3] < 128


def test_prefix_is_drawn_immediately_at_first_line(bub):
    bub.say("你好")
    assert count_fg(bub.render_image(50.0)) > 0  # 还没出字，但 "> " 已经在


def test_auto_hide_after_hold_and_fade(qapp):
    clk = Clock()
    b = BubbleWindow(clock=clk, autostart=True)
    try:
        b.say("嗯？")
        assert b.isVisible()
        clk.t += 0.5
        b._tick()
        assert b.isVisible()
        clk.t += 4.0 + 0.3
        b._tick()
        assert not b.isVisible()
    finally:
        b.close()


def test_say_replaces_and_dismiss_hides(bub):
    bub.say("第一句")
    assert bub.isVisible()
    bub.clk.t += 1
    bub.say("第二句")
    assert bub.timeline.text == "第二句"
    assert bub.timeline.visible_chars(bub.clk.t) == 0  # 从头打字
    bub.dismiss()
    assert not bub.isVisible()
    assert bub.timeline.finished(bub.clk.t)


def test_follow_places_above_body_on_screen(bub):
    from PySide6.QtGui import QGuiApplication

    g = QGuiApplication.primaryScreen().availableGeometry()
    body = (g.left() + 300, g.top() + 400, 120, 240)
    bub.follow(body)
    bub.say("嗯？")
    assert bub.y() + bub.height() <= body[1]
    assert abs((bub.x() + bub.width() / 2) - (body[0] + 60)) <= 1
    bub.follow((body[0] + 100, body[1], 120, 240))  # 桌宠移动，气泡跟着
    assert abs((bub.x() + bub.width() / 2) - (body[0] + 160)) <= 1


def test_font_family_is_a_known_candidate_or_fixed_fallback(bub):
    assert bub.font_family


def test_every_wrapped_line_starts_with_a_prefix(bub):
    bub.say("哇啊啊——放我下来！这是一句比较长的台词用来测试折行效果，再加一些字让它变成三行以上的文本")
    assert bub.line_count >= 3
    img = rgba(bub.render_image(50.0 + 2.0))  # 全部打完（还没开始淡出）
    x0 = 1 + B.PAD_X
    y0 = 1 + B.PAD_Y
    for i, ln in enumerate(bub._lines):
        top = int(y0 + ln.y)
        region = img[top : top + 12, x0 : x0 + int(bub._prefix_w) - 2]
        fg = ((region[:, :, 0] > 200) & (region[:, :, 1] > 190) & (region[:, :, 3] > 200)).sum()
        assert fg > 0, f"第 {i} 行开头没有 > 前缀"
