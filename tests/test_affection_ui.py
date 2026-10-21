"""真实控制器/Qt 信号下的好感度联调，不能替代桌面动态观感验收。"""
from datetime import timedelta
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from shion.affection import load_rules
from shion.effects import Celebration, MAX_PARTICLES
from shion.lines import Lines
from shion.speech import Priority
from shion.state import SaveData
from tests.test_controller import Env, T0, qapp


@pytest.fixture
def active(qapp, tmp_path):
    env = Env(tmp_path, affection=load_rules())
    env.data.activity_level = "quiet"
    yield env
    env.close()


def text_pool(env, key):
    return {item if isinstance(item, str) else item["text"] for item in env.ctl.lines._lines[key]}


@pytest.mark.parametrize("first,hook", [(True, False), (False, False), (False, True)])
def test_open_reward_once_per_date_even_when_hook_suppresses_greeting(active, first, hook):
    active.ctl.greet_startup(first, hook)
    assert active.data.affection == 2
    active.ctl.greet_startup(first, hook)
    assert active.data.affection == 2
    active.advance(86400)
    assert active.data.affection == 2  # 仅跨天，不凭空发打开奖励
    active.ctl.greet_startup(False, hook)
    assert active.data.affection == 4


@pytest.mark.parametrize("points", [49, 199, 499, 999])
def test_upgrade_interrupts_high_speech_and_full_hearts_exactly_once(qapp, tmp_path, points):
    env = Env(tmp_path, SaveData(affection=points), affection=load_rules())
    try:
        env.ctl.say("important", priority=Priority.HIGH)
        for i in range(6):
            env.overlay.particles.spawn(env.mono[0] + i * 0.2, start_session=True)
        assert len(env.overlay.particles.items(env.mono[0] + 0.8)) >= 4
        env.win.patted.emit()
        level = env.state.affection_level
        assert env.said[-1] == env.state.affection.levels[level - 1].upgrade["zh"]
        assert env.ctl._speech.priority == Priority.HIGH
        assert len(env.overlay.celebration.items(env.mono[0])) == Celebration.COUNT
        count = len(env.said)
        env.win.patted.emit()
        env.ctl.tick()
        assert len(env.said) == count
        assert env.overlay.celebration.born == env.mono[0]
        env.advance(2)
        env.overlay.tick()
        assert not env.overlay.celebration.items(env.mono[0])
    finally:
        env.close()


def test_celebration_is_independent_of_normal_particle_capacity_and_rate(active):
    now = active.mono[0]
    for _ in range(4):
        active.overlay.particles.spawn(now, start_session=True)
    assert len(active.overlay.particles.items(now)) == MAX_PARTICLES
    active.overlay.celebrate(active.win.head_anchor())
    assert len(active.overlay.particles.items(now)) == MAX_PARTICLES
    ring = active.overlay.celebration.items(now)
    assert len(ring) == 12 and len({(x, y) for x, y, _, _ in ring}) == 12
    assert active.overlay.windowFlags() & Qt.WindowTransparentForInput
    assert active.overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus


def test_muted_upgrade_still_updates_level_and_shows_hearts(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=49, bubble_muted=True), affection=load_rules())
    try:
        env.win.patted.emit()
        assert env.data.affection_level == 2 and not env.said
        assert env.overlay.celebration.items(env.mono[0])
        env.ctl._show_status()
        assert "熟悉" in env.said[-1]  # 双击状态仍不受静音限制
    finally:
        env.close()


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("points", [0, 50, 200, 500, 1000])
def test_status_level_progress_remaining_and_max(qapp, tmp_path, lang, points):
    env = Env(tmp_path, SaveData(affection=points), affection=load_rules())
    try:
        env.ctl.lines.set_language(lang)
        text = env.ctl.status_text()
        level = env.state.affection_level
        assert env.state.affection.levels[level - 1].name[lang] in text
        assert f"Lv.{level}" in text
        if level == 5:
            assert Lines(lang).ui("affection_max") in text
        else:
            interval = env.state.affection.levels[level].threshold - env.state.affection.levels[level - 1].threshold
            assert f"0/{interval}" in text
        expected = 32 + len(env.ctl.menu_content.visible("talks", level))
        assert str(expected) in text
        env.ctl.greet_startup(False)
        assert env.state.affection_remaining(env.now, [i.id for i in env.ctl.menu_content.visible("talks", level)]) == expected - 2
    finally:
        env.close()


def test_locked_selection_cannot_award_or_start_eating_and_numbers_have_no_gaps(active):
    for ident in ("stay_with_me", "listen_to_me", "stay_together"):
        active.ctl.choose_dialogue("talks", ident)
    active.ctl.choose_dialogue("snacks", "shared_chocolate")
    assert active.data.affection == 0 and not active.state.eating and not active.said
    active.ctl.open_dialogue()
    panel = active.ctl._dialogue
    assert sorted(panel._choices) == [1, 2, 3, 4]
    labels = [w.text() for w in panel.findChildren(QPushButton) if not w.isHidden()]
    assert not any("陪我一下" in text or "听我说说" in text for text in labels)


def test_open_menu_refreshes_after_unlock_and_deduplicates_dialogue_rewards(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=49), affection=load_rules())
    try:
        env.ctl.open_dialogue()
        env.win.patted.emit()
        env.ctl.tick()
        panel = env.ctl._dialogue
        assert panel.level == 2 and any(ident == "stay_with_me" for _, ident in panel._choices.values())
        env.ctl.choose_dialogue("talks", "stay_with_me")
        env.ctl.choose_dialogue("talks", "stay_with_me")
        env.ctl.choose_dialogue("talks", "headpat")
        assert env.data.affection == 52
        assert env.data.stats["pats"] == 1 and not env.data.feedback_queue
    finally:
        env.close()


def test_snack_completion_upgrades_once_through_controller(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=48), affection=load_rules())
    try:
        env.data.activity_level = "quiet"
        env.ctl.choose_dialogue("snacks", "cookie")
        assert env.data.affection == 48
        env.advance(2)
        assert env.data.affection == 50 and env.data.affection_level == 2
        assert env.said[-1] == env.state.affection.levels[1].upgrade["zh"]
        count = len(env.said)
        env.advance(2)
        assert len(env.said) == count
    finally:
        env.close()


def test_upgrade_remains_visible_when_nudge_is_due_on_same_tick(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=48), affection=load_rules())
    try:
        env.data.activity_level = "quiet"
        env.state.claude_event("stop", None, env.now)
        env.advance(298)
        env.ctl.choose_dialogue("snacks", "cookie")
        env.advance(2)
        assert env.said[-1] == env.state.affection.levels[1].upgrade["zh"]
        assert env.ctl._speech.priority == Priority.HIGH
    finally:
        env.close()


@pytest.mark.parametrize("key", ["pat", "neglect_return", "idle_talk"])
@pytest.mark.parametrize("points,level", [(0, 1), (50, 2), (200, 3), (500, 4), (1000, 5)])
def test_speech_uses_current_level_pool(qapp, tmp_path, points, level, key):
    env = Env(tmp_path, SaveData(affection=points), affection=load_rules())
    try:
        env.state.affection = replace(env.state.affection, rare_chance=0)
        assert env.ctl.say_key(key)
        assert env.said[-1] in text_pool(env, f"{key}_level_{level}")
        env.ctl.set_muted(True)
        assert not env.ctl.say_key(key)
    finally:
        env.close()


def test_rare_thanks_respects_max_level_chance_cooldown_and_speech_gate(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=1000), affection=load_rules())
    try:
        env.state.affection = replace(env.state.affection, rare_chance=1)
        env.ctl.say("busy", priority=Priority.HIGH)
        assert not env.ctl.say_key("idle_talk")
        assert env.ctl._last_rare_idle == -float("inf")
        env.ctl._speech.dismiss()
        assert env.ctl.say_key("idle_talk")
        assert env.said[-1] in text_pool(env, "idle_thanks")
        first = env.mono[0]
        env.mono[0] += 10
        env.ctl._speech.dismiss()
        env.ctl.say_key("idle_talk")
        assert env.said[-1] in text_pool(env, "idle_talk_level_5")
        env.mono[0] = first + env.state.affection.rare_cooldown
        env.ctl._speech.dismiss()
        env.ctl.say_key("idle_talk")
        assert env.said[-1] in text_pool(env, "idle_thanks")
    finally:
        env.close()


def test_fallback_keeps_old_status_and_generic_line_pools(qapp, tmp_path):
    env = Env(tmp_path, SaveData(affection=1000), affection=None)
    try:
        assert "Lv." not in env.ctl.status_text()
        assert env.ctl.say_key("pat") and env.said[-1] in text_pool(env, "pat")
        env.ctl.choose_dialogue("talks", "stay_with_me")
        assert env.data.affection == 1000
    finally:
        env.close()
