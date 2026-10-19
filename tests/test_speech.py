"""用假时钟验证气泡仲裁、冷却与连续摸头，不依赖真实等待。"""
import pytest

from shion.speech import (
    CHAR_INTERVAL, FADE, HOLD, LOW_CATEGORY_COOLDOWN, LOW_MIN_VISIBLE,
    PAT_REPEAT_AFTER, PAT_SESSION_GAP, PatSession, Priority, SpeechGate, speech_kind,
)


@pytest.mark.parametrize("current", list(Priority))
@pytest.mark.parametrize("incoming", list(Priority))
@pytest.mark.parametrize("age", [0.1, LOW_MIN_VISIBLE])
def test_priority_matrix(current, incoming, age):
    gate = SpeechGate()
    assert gate.start(100, "当前台词", current, "old")
    expected = incoming == Priority.HIGH or (
        current == Priority.LOW and (incoming == Priority.MEDIUM or age >= LOW_MIN_VISIBLE)
    )
    assert gate.start(100 + age, "新台词", incoming, "new") == expected


def test_same_low_category_cooldown_uses_only_accepted_speech():
    gate = SpeechGate()
    assert gate.start(100, "摸头", Priority.LOW, "pat")
    assert not gate.start(102.499, "拖动", Priority.LOW, "drag")
    assert gate.start(102.5, "拖动", Priority.LOW, "drag")
    assert not gate.start(103.999, "摸头", Priority.LOW, "pat")
    # 当前 drag 也须显示满 2.5 秒；被拒的 pat 不会刷新任一计时。
    assert not gate.start(104, "摸头", Priority.LOW, "pat")
    assert gate.start(105, "摸头", Priority.LOW, "pat")
    gate.dismiss()
    assert not gate.start(105 + LOW_CATEGORY_COOLDOWN - 0.001, "摸头", Priority.LOW, "pat")
    assert gate.start(105 + LOW_CATEGORY_COOLDOWN, "摸头", Priority.LOW, "pat")


@pytest.mark.parametrize("priority", [Priority.MEDIUM, Priority.HIGH])
def test_priority_lasts_through_typing_hold_and_fade(priority):
    gate = SpeechGate()
    text = "长" * 200 + "\r\n第二行"
    end = 100 + len(text.replace("\r\n", "\n")) * CHAR_INTERVAL + HOLD + FADE
    assert gate.start(100, text, priority, "event")
    assert not gate.start(end - 0.001, "摸头", Priority.LOW, "pat")
    assert gate.start(end, "摸头", Priority.LOW, "pat")


def test_high_interrupts_high_without_category_cooldown():
    gate = SpeechGate()
    for _ in range(5):
        assert gate.start(100, "出错了", Priority.HIGH, "error")
    assert not gate.start(103, "问候", Priority.MEDIUM, "greeting")
    gate.dismiss()
    assert gate.start(103, "问候", Priority.MEDIUM, "greeting")


def test_empty_or_rejected_speech_does_not_change_the_current_bubble():
    gate = SpeechGate()
    assert not gate.start(100, "", Priority.HIGH, "empty")
    assert gate.start(100, "完成", Priority.HIGH, "done")
    before = (gate.priority, gate.started, gate.until, dict(gate.last_low))
    assert not gate.start(101, "戳", Priority.LOW, "poke")
    assert (gate.priority, gate.started, gate.until, gate.last_low) == before


@pytest.mark.parametrize("key", ["claude_done", "tool_error", "nudge", "claude_waiting", "permission_request"])
def test_critical_event_categories_are_high(key):
    assert speech_kind(key) == (Priority.HIGH, key)


def test_poke_variants_share_one_low_category():
    assert {speech_kind(key) for key in ("poke", "stop", "dizzy")} == {(Priority.LOW, "poke")}


def test_pat_session_inclusive_gap_strict_repeat_and_no_further_repetition():
    session = PatSession()
    assert session.feed(100)
    assert session.new_session
    for i in range(1, 7):
        assert not session.feed(100 + i * PAT_SESSION_GAP)
    assert not session.feed(100 + PAT_REPEAT_AFTER)
    assert session.feed(100 + PAT_REPEAT_AFTER + 0.001)
    assert not session.new_session
    for i in range(7, 20):
        assert not session.feed(100 + i)
    assert session.feed(120.001)  # 距上次 >1 秒，开始新过程。
    assert session.new_session


def test_quick_new_pat_session_still_obeys_four_second_speech_cooldown():
    session, gate = PatSession(), SpeechGate()
    assert session.feed(100) and gate.start(100, "摸头", Priority.LOW, "pat")
    assert session.feed(101.001)
    assert not gate.start(101.001, "再摸头", Priority.LOW, "pat")
    assert session.feed(104)
    assert gate.start(104, "摸头", Priority.LOW, "pat")
