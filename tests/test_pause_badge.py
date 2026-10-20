"""停下标记 ⏸ 与检查点 hook 的 statusMessage。"""
import json
import threading
import time

import pytest
from PySide6.QtGui import QColor

from shion import badge as B
from shion.lines import LINES_DIR
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
    s = 20
    x, y = B.badge_geometry(BODY, s, AVAIL)
    assert BODY[0] + BODY[2] * 0.6 < x + s / 2 < BODY[0] + BODY[2]  # 头顶右侧
    assert BODY[1] - s < y < BODY[1] + BODY[3] * 0.15  # 和头顶同高，不在气泡所在的正上方区域
    # 气泡在本体上方居中，标记中心离精灵中线足够远
    assert abs((x + s / 2) - (BODY[0] + BODY[2] / 2)) > BODY[2] * 0.2


def test_geometry_moves_up_with_jump_and_is_clamped():
    s = 20
    _, y0 = B.badge_geometry(BODY, s, AVAIL)
    _, y1 = B.badge_geometry(BODY, s, AVAIL, jump_offset=30)
    assert y1 == y0 - 30
    x, y = B.badge_geometry((1850, -50, 200, 230), s, AVAIL)
    assert x == 1920 - s and y == 0


def test_size_scales_and_is_bounded():
    assert B.badge_size(100) == B.BADGE_MIN
    assert B.badge_size(2000) == B.BADGE_MAX
    assert B.BADGE_MIN <= B.badge_size(400) <= B.BADGE_MAX


def test_render_draws_two_bars(qapp):  # noqa: F811
    s = 24
    img = B.render_badge(s)
    mid = s // 2
    bar = QColor(img.pixel(round(s * 0.37), mid))
    gap = QColor(img.pixel(mid, mid))
    assert bar.lightness() > 200 and gap.lightness() < 80  # 两根亮竖条，中间是深色底
    assert QColor(img.pixel(round(s * 0.63), mid)).lightness() > 200
    assert img.pixelColor(0, 0).alpha() < 128  # 圆角外透明


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
