"""暂停文字标签的可见性、鼠标防误点、焦点与检查点放行。"""
import json
import threading
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from shion import badge as B
from shion.lines import LINES_DIR
from shion.bubble import BubbleWindow, FONT_PX, FG, BORDER, BG
from shion.panel import ARM_DELAY
from tests.test_controller import env, qapp  # noqa: F401
from tests.test_install_hooks import PY, SCRIPT, hc
from tests.test_interrupt import pet2, work  # noqa: F401
from tests.test_stop_work import held, join, pet, start_waiters  # noqa: F401

STATUS = {
    "zh": "诗音在看着～（一直停在这里就是暂停了，右键诗音点继续）",
    "en": "Shion is watching~ (stuck here = paused; right-click Shion → Continue)",
    "ja": "詩音が見てるよ～（ここで止まったままなら一時停止中。詩音を右クリックして「続ける」）",
}


def shown(p):
    return p.win.paused_badge_shown


# ---------------------------------------------------------------- 控制器：什么时候显示
def test_not_shown_until_a_hook_really_waits(pet):
    pet.ctl.stop_work()
    for _ in range(5):
        pet.advance(0.2)
    assert pet.state.paused and not shown(pet)  # 点了停下，还没到检查点
    threads, _ = start_waiters(pet.ctl.hub)
    pet.advance(0.1)
    assert shown(pet)
    pet.ctl.resume_work()
    join(threads)
    assert not shown(pet)


def test_stays_through_gaps_between_long_polls_and_other_lines(pet):
    threads, _ = held(pet)
    assert shown(pet)
    pet.ctl.hub.resume()
    join(threads)
    pet.ctl.hub.pause()  # 模拟两段长轮询之间：hub 仍停着，但此刻没有 hook 在等
    pet.ctl.hub._last_hold -= 10
    assert not pet.ctl.hub.is_holding
    pet.ctl.say_text("别的台词")
    for _ in range(10):
        pet.advance(0.5)
    assert shown(pet)


def test_shown_even_when_muted(pet):
    pet.ctl.set_muted(True)
    threads, _ = held(pet)
    assert pet.said == [] and shown(pet)
    pet.ctl.resume_work(quiet=True)
    join(threads)
    assert not shown(pet)


def test_hidden_when_user_speaks_in_cc(pet):
    threads, _ = held(pet)
    pet.ctl.hub.resume()  # 服务线程收到 prompt 时做的
    pet.ctl.handle_event("prompt")
    join(threads)
    assert not shown(pet)
    pet.ctl.stop_work()  # 下一次停下：没到检查点前仍不显示
    assert not shown(pet)


def test_hidden_after_pause_timeout(pet):
    threads, _ = held(pet)
    pet.ctl.handle_event("pause_timeout")
    join(threads)
    assert not shown(pet)


def test_hidden_after_interrupt_releases_the_stop(pet2):
    work(pet2)
    pet2.ctl.stop_work()
    results = []
    t = threading.Thread(target=lambda: results.append(pet2.ctl.hub.wait_gate(5, "s1")), daemon=True)
    t.start()
    deadline = time.monotonic() + 3
    while pet2.ctl.hub._holding < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    pet2.advance(0.1)
    assert shown(pet2)
    pet2.ctl.interrupt_work()
    t.join(5)
    assert not shown(pet2)


def test_badge_window_follows_pet_visibility(pet):
    threads, _ = held(pet)
    pet.win.show()
    badge = pet.win._pause_badge
    badge.refresh()
    assert badge.isVisible()
    pet.win.hide()
    assert not badge.isVisible()
    pet.win.show()
    assert badge.isVisible()
    pet.ctl.resume_work()
    join(threads)
    assert not badge.isVisible()
    pet.win.hide()


# ---------------------------------------------------------------- 位置与画面
BODY = (100, 200, 200, 230)
AVAIL = (0, 0, 1920, 1080)


def test_geometry_is_at_head_top_right_not_above_head():
    size = (90, 28)
    x, y = B.badge_geometry(BODY, size, AVAIL)
    assert BODY[0] + BODY[2] * 0.6 < x + size[0] / 2 < BODY[0] + BODY[2]
    assert BODY[1] - size[1] < y < BODY[1] + BODY[3] * 0.15
    # 气泡在本体上方居中，标记中心离精灵中线足够远
    assert abs((x + size[0] / 2) - (BODY[0] + BODY[2] / 2)) > BODY[2] * 0.2


def test_geometry_moves_up_with_jump_and_is_clamped():
    size = (100, 28)
    _, y0 = B.badge_geometry(BODY, size, AVAIL)
    _, y1 = B.badge_geometry(BODY, size, AVAIL, jump_offset=30)
    assert y1 == y0 - 30
    x, y = B.badge_geometry((1850, -50, 200, 230), size, AVAIL)
    assert x == 1920 - size[0] and y == 0


@pytest.mark.parametrize("text", ["暂停中", "Paused", "一時停止中"])
def test_size_fits_localized_text_with_bubble_font(qapp, text):
    font = B.label_font()
    w, h = B.badge_size(text, font)
    assert w > QFontMetricsF(font).horizontalAdvance(text)
    assert h > QFontMetricsF(font).height()
    assert font.pixelSize() == FONT_PX


def test_render_draws_terminal_border_background_and_text(qapp):
    img = B.render_badge("Paused", B.label_font())
    assert img.pixelColor(0, 0).alpha() < 128
    assert img.pixelColor(8, img.height() // 2) == BG
    colors = {img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())}
    assert FG.name() in colors and BORDER.name() in colors


@pytest.mark.parametrize("delay,accepted", [(0, False), (ARM_DELAY - .001, False), (ARM_DELAY, True)])
def test_left_click_arms_after_delay_and_resumes_all_checkpoints(pet, delay, accepted):
    pet.win.show()
    threads, results = held(pet, n=2)
    badge = pet.win._pause_badge
    try:
        pet.advance(delay)
        QTest.mouseClick(badge, Qt.LeftButton, Qt.NoModifier, badge.rect().center())
        assert pet.state.paused is not accepted
        assert shown(pet) is not accepted
        if accepted:
            join(threads)
            assert results == [(False, False)] * 2
            assert pet.said[-1] in pet.ctl.lines._lines["resumed"]
            assert not badge.isVisible()
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)


def test_press_before_arming_release_after_does_not_resume(pet):
    pet.win.show()
    threads, _ = held(pet)
    badge = pet.win._pause_badge
    try:
        QTest.mousePress(badge, Qt.LeftButton, Qt.NoModifier, badge.rect().center())
        pet.advance(ARM_DELAY + .1)
        QTest.mouseRelease(badge, Qt.LeftButton, Qt.NoModifier, badge.rect().center())
        assert pet.state.paused
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)


def test_only_left_mouse_works_and_label_mask_leaves_other_regions_clear(pet):
    pet.win.show()
    threads, _ = held(pet)
    badge = pet.win._pause_badge
    try:
        pet.advance(ARM_DELAY)
        for button in (Qt.RightButton, Qt.MiddleButton):
            QTest.mouseClick(badge, button, Qt.NoModifier, badge.rect().center())
        for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
            QTest.keyClick(badge, key)
        # 区域外释放也不能继续。
        QTest.mousePress(badge, Qt.LeftButton, Qt.NoModifier, badge.rect().center())
        QTest.mouseRelease(badge, Qt.LeftButton, Qt.NoModifier, QPoint(-10, -10))
        assert pet.state.paused
        assert badge.windowFlags() & Qt.WindowDoesNotAcceptFocus
        assert not badge.windowFlags() & Qt.WindowTransparentForInput
        assert badge.testAttribute(Qt.WA_ShowWithoutActivating)
        assert badge.focusPolicy() == Qt.NoFocus
        assert badge.contextMenuPolicy() == Qt.PreventContextMenu
        assert badge.mask().contains(badge.rect().center())
        assert not badge.mask().contains(QPoint(0, 0))
        assert not badge.mask().contains(QPoint(-10, -10))
        assert not pet.win.mask().contains(QPoint(0, 0))
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)


@pytest.mark.parametrize("lang,text,hint", [("zh", "暂停中", "点一下继续"), ("en", "Paused", "Click to continue"),
                                           ("ja", "一時停止中", "クリックして再開")])
def test_visible_label_updates_language_font_tooltip_and_follows_resize(pet, lang, text, hint):
    pet.win.show()
    threads, _ = held(pet)
    try:
        pet.ctl.set_language(lang)
        badge = pet.win._pause_badge
        assert badge.text == text and badge.toolTip() == hint
        raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        assert raw["ui"]["pause_label"] == text and raw["ui"]["pause_label_hint"] == hint
        bubble = BubbleWindow(autostart=False)
        bubble.set_font_fallback(pet.ctl.lines.font_fallback)
        assert badge.font().families() == bubble._font.families()
        bubble.close()
        pet.win.set_height(320)
        pet.win.move(200, 200)
        badge.follow()
        avail = pet.win._screen_avail()
        expected = B.badge_geometry(pet.win.body_rect(), (badge.width(), badge.height()),
                                   (avail.x(), avail.y(), avail.width(), avail.height()))
        assert (badge.x(), badge.y()) == expected
        assert "claude" not in (text + hint).lower()
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)


def test_showing_label_keeps_typing_focus_in_other_window(pet, qapp):
    if qapp.platformName() == "offscreen":
        pytest.skip("offscreen 不实现非激活显示；本项已由原生 Windows 150% 回归验证")
    pet.win.show()
    qapp.processEvents()
    edit = QLineEdit()
    edit.show()
    edit.activateWindow()
    edit.setFocus()
    qapp.processEvents()
    focused = qapp.focusWidget()
    assert focused is edit and qapp.activeWindow() is edit
    threads, _ = held(pet)
    try:
        qapp.processEvents()
        assert qapp.focusWidget() is focused
        assert qapp.activeWindow() is edit
        QTest.keyClicks(edit, "still typing")
        assert edit.text() == "still typing" and pet.state.paused
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)
        edit.close()


def test_reshowing_label_rearms_and_repeated_sync_does_not_reset_delay(pet):
    pet.win.show()
    threads, _ = held(pet)
    badge = pet.win._pause_badge
    try:
        deadline = badge._armed_at
        for _ in range(8):
            pet.advance(.1)
        assert badge._armed_at == deadline
        pet.win.hide()
        pet.win.show()
        assert badge._armed_at > pet.mono[0]
        QTest.mouseClick(badge, Qt.LeftButton, Qt.NoModifier, badge.rect().center())
        assert pet.state.paused
    finally:
        pet.ctl.resume_work(quiet=True)
        join(threads)


# ---------------------------------------------------------------- statusMessage
def test_status_message_only_on_checkpoints():
    out = hc.merge({}, PY, SCRIPT, STATUS["zh"])
    for event in hc.EVENTS:
        entry = out["hooks"][event][0]["hooks"][0]
        if event in ("PreToolUse", "PostToolUse"):
            assert entry["statusMessage"] == STATUS["zh"]
        else:
            assert "statusMessage" not in entry
    assert hc.merge(out, PY, SCRIPT, STATUS["zh"]) == out  # 重装不重复
    assert hc.remove(out) == {}
    assert all("statusMessage" not in h for g in hc.merge({}, PY, SCRIPT)["hooks"].values()
               for x in g for h in x["hooks"])  # 旧调用方式不加


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_status_message_texts(lang):
    assert hc.status_message(lang) == STATUS[lang]
    raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    menu_resume = raw["ui"]["menu_resume"]
    assert menu_resume in STATUS[lang]  # 提到的按钮名和菜单一致
    assert "claude" not in STATUS[lang].lower()


def test_status_message_falls_back_to_chinese(tmp_path):
    assert hc.status_message("xx") == hc.STATUS_DEFAULT == STATUS["zh"]
    assert hc.status_message("en", root=tmp_path) == STATUS["zh"]


@pytest.mark.parametrize("save, expect", [
    ({"language": "ja"}, "ja"), ({"language": "en"}, "en"), ({"language": "fr"}, "zh"), ({}, "zh"), (None, "zh"),
])
def test_save_language(tmp_path, monkeypatch, save, expect):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    if save is not None:
        (tmp_path / "state.json").write_text(json.dumps(save), encoding="utf-8")
    assert hc.save_language() == expect


def test_install_writes_status_in_save_language(tmp_path, monkeypatch):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    settings = tmp_path / "settings.json"
    assert hc.run("install", str(settings), PY, SCRIPT) == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["statusMessage"] == STATUS["en"]
    assert hc.run("install", str(settings), PY, SCRIPT, lang="ja") == 0  # 换语言重装：替换，不重复
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["hooks"]["PostToolUse"]) == 1
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["statusMessage"] == STATUS["ja"]
