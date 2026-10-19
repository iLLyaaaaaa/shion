"""v0.3 工作遥控（第一部分）：暂停/继续、反馈队列。"""
import json
import threading
import time
import urllib.request

import pytest

from shion.bubble import BubbleTimeline
from shion.remote import MAX_WAIT, RemoteHub
from shion.server import ShionServer
from shion.speech import Priority, SpeechGate
from tests.test_controller import env, qapp, find_action  # noqa: F401


# ---------------------------------------------------------------- RemoteHub
def test_hub_pause_resume_and_wait():
    hub = RemoteHub()
    assert hub.is_paused is False
    assert hub.wait_while_paused(5) is False  # 没暂停：立刻返回
    hub.pause()
    t0 = time.monotonic()
    assert hub.wait_while_paused(0.2) is True  # 暂停中：等满时限仍然暂停
    assert 0.15 <= time.monotonic() - t0 < 2
    threading.Timer(0.2, hub.resume).start()
    t0 = time.monotonic()
    assert hub.wait_while_paused(5) is False  # 被 resume 唤醒，不用等满
    assert time.monotonic() - t0 < 2


def test_hub_wait_is_clamped():
    hub = RemoteHub()
    hub.pause()
    t0 = time.monotonic()
    assert hub.wait_while_paused(-5) is True and time.monotonic() - t0 < 1
    assert MAX_WAIT == 30.0


# ---------------------------------------------------------------- HTTP 接口
def post(srv, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}", data=json.dumps(body or {}).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


@pytest.fixture
def server():
    events = []
    hub = RemoteHub()
    srv = ShionServer(lambda t, d: events.append((t, d)), lambda: "", port=0, hub=hub)
    srv.start()
    yield srv, events, hub
    hub.resume()
    srv.stop()


def test_pause_wait_reports_state(server):
    srv, _, hub = server
    assert post(srv, "/pause/wait", {"wait": 0}) == (200, {"paused": False})
    hub.pause()
    assert post(srv, "/pause/wait", {"wait": 0}) == (200, {"paused": True})
    t0 = time.monotonic()
    assert post(srv, "/pause/wait", {"wait": 0.3}) == (200, {"paused": True})
    assert time.monotonic() - t0 >= 0.25
    threading.Timer(0.2, hub.resume).start()
    assert post(srv, "/pause/wait", {"wait": 10}) == (200, {"paused": False})


@pytest.mark.parametrize("wait", ["10", None, True, [], {}, float("nan"), float("inf")])
def test_pause_wait_ignores_bad_wait_values(server, wait):
    srv, _, hub = server
    hub.pause()
    t0 = time.monotonic()
    assert post(srv, "/pause/wait", {"wait": wait}) == (200, {"paused": True})
    assert time.monotonic() - t0 < 3  # 坏值当 0 处理，不会挂住


def test_prompt_event_resumes_pause_in_server_thread(server):
    srv, events, hub = server
    hub.pause()
    assert post(srv, "/event", {"type": "prompt"})[0] == 200
    assert hub.is_paused is False
    assert events == [("prompt", None)]


def test_http_cannot_start_or_keep_pause(server):
    """暂停只能由诗音界面发起；HTTP 里没有任何能“设置暂停”的接口。"""
    srv, events, hub = server
    for body in ({"paused": True}, {"pause": True}, {"wait": 0, "paused": True}):
        post(srv, "/pause/wait", body)
    for etype in ("pause", "paused", "pause_timeout", "resume"):
        post(srv, "/event", {"type": etype})
    assert hub.is_paused is False


def test_pause_wait_rejects_web_origin(server):
    srv, _, hub = server
    hub.pause()
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/pause/wait", data=b"{}", method="POST",
        headers={"Origin": "http://evil.example"},
    )
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403


# ---------------------------------------------------------------- 发言规则
def test_sticky_speech_never_expires_but_can_be_replaced():
    gate = SpeechGate()
    assert gate.start(10.0, "暂停中", Priority.MEDIUM, "paused", sticky=True)
    assert gate.until == float("inf") and gate.sticky
    assert gate.allows(10.0 + 2.6, Priority.LOW, "pat")  # 低优先级在满 2.5 秒后可以盖掉
    assert gate.allows(10.1, Priority.MEDIUM, "resumed")  # 中、高优先级随时可以
    assert gate.start(20.0, "好", Priority.MEDIUM, "resumed")
    assert gate.sticky is False and gate.until < 100  # 被替换后恢复正常计时
    gate.start(30.0, "暂停中", Priority.MEDIUM, "paused", sticky=True)
    gate.dismiss()
    assert gate.sticky is False and gate.until == 0.0


def test_sticky_bubble_timeline_never_fades():
    t = BubbleTimeline()
    t.start(0.0, "暂停中", sticky=True)
    assert t.opacity(1000.0) == 1.0 and not t.finished(1000.0)
    t.start(0.0, "普通")
    assert t.finished(100.0)
    t.start(0.0, "暂停中", sticky=True)
    t.clear()
    assert not t.sticky and t.finished(0.0)


# ---------------------------------------------------------------- 控制器：暂停
@pytest.fixture
def pet(env):  # noqa: F811
    env.sticky = []

    def say(text, sticky=False):
        env.said.append(text)
        if sticky:
            env.sticky.append(text)

    env.ctl._say_fn = say
    return env


def test_pause_shows_stop_sprite_and_sticky_bubble(pet):
    pet.ctl.pause_work()
    assert pet.ctl.hub.is_paused and pet.state.paused
    assert pet.win.sprite_name == "stop"
    assert pet.sticky == ["暂停中"]
    for _ in range(50):  # 一直挂着：不会反复重说
        pet.advance(1.0)
    assert pet.sticky == ["暂停中"]
    assert pet.win.sprite_name == "stop"


def test_pause_bubble_comes_back_after_being_replaced(pet):
    pet.ctl.pause_work()
    pet.advance(3.0)
    pet.ctl.say("别的话", priority=Priority.MEDIUM, category="x")
    assert pet.sticky == ["暂停中"]
    pet.advance(1.0)
    assert pet.sticky == ["暂停中"]  # 别的话还没说完
    pet.advance(10.0)
    assert pet.sticky == ["暂停中", "暂停中"]  # 说完后恢复


def test_resume_clears_pause_and_says_something(pet):
    pet.ctl.pause_work()
    pet.ctl.resume_work()
    assert not pet.ctl.hub.is_paused and not pet.state.paused
    assert pet.win.sprite_name != "stop"
    assert pet.said[-1] in pet.ctl.lines._lines["resumed"]
    for _ in range(20):
        pet.advance(1.0)
    assert pet.sticky == ["暂停中"]  # 没有再冒出来


def test_prompt_from_cc_releases_pause_on_gui_side(pet):
    pet.ctl.pause_work()
    pet.ctl.hub.resume()  # 服务线程收到 prompt 事件时做的
    pet.ctl.handle_event("prompt")
    assert not pet.state.paused and pet.win.sprite_name != "stop"
    pet.advance(5.0)
    assert pet.sticky == ["暂停中"]


def test_pause_timeout_keeps_pause_and_changes_notice(pet):
    pet.ctl.pause_work()
    pet.ctl.handle_event("pause_timeout")
    assert pet.state.paused and pet.ctl.hub.is_paused
    assert pet.sticky[-1] == "已经停下了，在 CC 里说一声就能继续"
    pet.ctl.resume_work()  # 之后点“继续”只是解除标记
    assert not pet.state.paused and not pet.ctl.hub.is_paused


def test_pause_timeout_ignored_when_not_paused(pet):
    pet.ctl.handle_event("pause_timeout")
    assert pet.sticky == [] and not pet.state.paused


def test_muted_pause_shows_no_bubble_but_still_pauses(pet):
    pet.ctl.set_muted(True)
    pet.ctl.pause_work()
    pet.advance(3.0)
    assert pet.said == [] and pet.ctl.hub.is_paused and pet.win.sprite_name == "stop"


def test_menu_offers_pause_or_resume(pet):
    menu = pet.ctl.build_menu()
    remote = find_action(menu, "工作遥控").menu()
    assert [a.text() for a in remote.actions()] == ["暂停工作", "做得好", "有问题……"]
    find_action(remote, "暂停工作").trigger()
    assert pet.ctl.hub.is_paused
    menu2 = pet.ctl.build_menu()
    remote2 = find_action(menu2, "工作遥控").menu()
    assert [a.text() for a in remote2.actions()] == ["继续工作", "做得好", "有问题……"]
    find_action(remote2, "继续工作").trigger()
    assert not pet.ctl.hub.is_paused


def test_new_ui_text_never_mentions_claude():
    import json as _json
    from shion.lines import LINES_DIR

    keys = ["menu_remote", "menu_pause", "menu_resume", "menu_good", "menu_bad", "panel_bad_title",
            "panel_send", "panel_cancel", "paused_status", "paused_timeout"]
    for lang in ("zh", "en", "ja"):
        raw = _json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert raw["ui"][k] and "claude" not in raw["ui"][k].lower()
        for k in ("feedback_sent", "feedback_bad", "resumed"):
            assert raw["lines"][k] and all("claude" not in x.lower() for x in raw["lines"][k])


# ---------------------------------------------------------------- 控制器：反馈
def test_take_feedback_text_says_delivered_only_when_something_sent(pet):
    assert pet.ctl.take_feedback_text() == "" and pet.said == []
    pet.ctl.feedback_good()
    pet.said.clear()
    pet.advance(20.0)
    assert pet.ctl.take_feedback_text() == "[诗音] 用户觉得你刚才做得很好。"
    assert pet.said[-1] in pet.ctl.lines._lines["feedback_sent"]


def test_take_feedback_respects_inject_praise_false(pet):
    pet.data.inject_praise = False
    pet.ctl.feedback_good()
    assert pet.ctl.take_feedback_text() == ""
    assert pet.data.feedback_queue == []  # 仍被清空
    assert not any(x in pet.ctl.lines._lines["feedback_sent"] for x in pet.said)


@pytest.mark.parametrize("lang,good,bad,plain", [
    ("zh", "[诗音] 用户觉得你刚才做得很好。", "[诗音] 用户认为刚才的改动有问题：不对。请重新检查。",
     "[诗音] 用户认为刚才的改动有问题。请重新检查。"),
    ("en", "[Shion] The user thinks you did a great job just now.",
     "[Shion] The user thinks the recent change has a problem: 不对. Please re-check.",
     "[Shion] The user thinks the recent change has a problem. Please re-check."),
])
def test_feedback_text_is_localized(pet, lang, good, bad, plain):
    pet.ctl.set_language(lang)
    pet.ctl.feedback_good()
    pet.ctl.feedback_good()
    pet.ctl.feedback_bad("不对")
    pet.ctl.feedback_bad("")
    assert pet.ctl.take_feedback_text().splitlines() == [good, bad, plain]


def test_bad_feedback_panel_submit_and_cancel(pet):
    pet.ctl.open_bad_feedback()
    panel = pet.ctl._input_panel
    assert panel.isVisible()
    panel._edit.setText("  测试没过 ")
    panel._ok.click()
    assert not panel.isVisible()
    assert pet.data.feedback_queue == [{"kind": "bad", "text": "测试没过"}]
    assert pet.said[-1] in pet.ctl.lines._lines["feedback_bad"]
    pet.ctl.open_bad_feedback()
    panel._edit.setText("不会发")
    panel._cancel.click()
    assert len(pet.data.feedback_queue) == 1
    pet.ctl.open_bad_feedback()
    panel._ok.click()  # 留空也可以发送
    assert pet.data.feedback_queue[-1] == {"kind": "bad", "text": ""}
    panel.close()


def test_panel_text_is_localized(pet):
    pet.ctl.set_language("en")
    pet.ctl.open_bad_feedback()
    panel = pet.ctl._input_panel
    assert panel._ok.text() == "Send" and panel._cancel.text() == "Cancel"
    assert panel._title.text() == "What's wrong? (optional)"
    panel.close()
