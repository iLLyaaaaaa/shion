from datetime import datetime, timedelta

import pytest

from shion.state import Config, PetState, SaveData

T0 = datetime(2026, 10, 19, 12, 0, 0)  # 白天


def sec(n):
    return timedelta(seconds=n)


def keys(reactions):
    return [r.key for r in reactions]


@pytest.fixture
def pet():
    return PetState(SaveData(), T0)


def test_starts_idle(pet):
    assert pet.current(T0) == "idle"


# ---- 优先级 ----

def test_drag_beats_everything(pet):
    pet.claude_event("working", None, T0)
    pet.pat(T0)
    pet.drag_start(T0)
    assert pet.current(T0) == "drag"
    pet.drag_end(T0 + sec(0.1))
    assert pet.current(T0 + sec(0.1)) == "happy"  # 松手后回到更低优先级的临时状态


def test_temp_beats_working(pet):
    pet.claude_event("working", None, T0)
    assert pet.current(T0) == "working"
    pet.pat(T0)
    assert pet.current(T0) == "happy"
    assert pet.current(T0 + sec(2)) == "working"  # happy 到期后回到 working


def test_working_beats_sleep():
    p = PetState(SaveData(), T0)
    t = T0 + timedelta(minutes=20)  # 已经空闲到该睡了
    assert p.current(t) == "sleep"
    p.claude_event("working", None, t)
    assert p.current(t + sec(1)) == "working"


# ---- 临时状态 ----

@pytest.mark.parametrize("seconds, expected", [(1.4, "happy"), (1.6, "idle")])
def test_pat_happy_expires(pet, seconds, expected):
    pet.pat(T0)
    assert pet.current(T0 + sec(seconds)) == expected


def test_done_lasts_3s_and_counts_task(pet):
    pet.claude_event("working", None, T0)
    r = pet.claude_event("stop", None, T0 + sec(5))
    assert "claude_done" in keys(r)
    assert pet.current(T0 + sec(7)) == "done"
    assert pet.current(T0 + sec(8.1)) == "idle"
    assert pet.save.stats["claude_tasks"] == 1


def test_praise_menu_proud_and_affection(pet):
    r = pet.feedback_good(T0)
    assert keys(r) == ["praise_menu"]
    assert pet.save.affection == 3
    assert pet.current(T0 + sec(2.9)) == "proud"
    assert pet.current(T0 + sec(3.1)) == "idle"


def test_tick_clears_expired(pet):
    pet.pat(T0)
    pet.tick(T0 + sec(5))
    assert pet._temp is None


# ---- working ----

def test_working_times_out_after_2_minutes(pet):
    pet.claude_event("working", None, T0)
    assert pet.current(T0 + sec(119)) == "working"
    assert pet.current(T0 + sec(121)) == "idle"


def test_working_renewed_by_new_event(pet):
    pet.claude_event("working", None, T0)
    r = pet.claude_event("working", None, T0 + sec(100))
    assert "claude_working" not in keys(r)  # 已在 working，不重复说话
    assert pet.current(T0 + sec(200)) == "working"
    assert pet.current(T0 + sec(221)) == "idle"


def test_first_working_says_line(pet):
    assert "claude_working" in keys(pet.claude_event("working", None, T0))


def test_stop_ends_working(pet):
    pet.claude_event("working", None, T0)
    pet.claude_event("stop", None, T0 + sec(10))
    assert pet.current(T0 + sec(14)) == "idle"


# ---- 睡眠 ----

def test_sleep_after_15_min_idle(pet):
    assert pet.current(T0 + timedelta(minutes=14)) != "sleep"
    assert pet.current(T0 + timedelta(minutes=15)) == "sleep"


def test_wake_says_line_and_resets_idle(pet):
    t = T0 + timedelta(minutes=20)
    r = pet.interact(t)
    assert keys(r) == ["wake"]
    assert pet.current(t) == "idle"
    assert pet.current(t + timedelta(minutes=14)) != "sleep"  # interact 不算被理会，冷落照常累积
    assert pet.current(t + timedelta(minutes=15)) == "sleep"


def test_interact_while_awake_no_wake_line(pet):
    assert pet.interact(T0 + sec(30)) == []


def test_claude_event_wakes(pet):
    r = pet.claude_event("session_start", None, T0 + timedelta(minutes=20))
    assert "wake" in keys(r)
    assert "greeting" in keys(r)


NIGHT = datetime(2026, 10, 20, 1, 0, 0)


def test_asleep_at_night_even_if_recently_active():
    p = PetState(SaveData(), NIGHT - sec(10))
    assert p.current(NIGHT) == "sleep"


def test_night_boundaries():
    p = PetState(SaveData(), datetime(2026, 10, 20, 0, 29))
    assert p.current(datetime(2026, 10, 20, 0, 29, 30)) == "idle"
    assert p.current(datetime(2026, 10, 20, 0, 30)) == "sleep"
    q = PetState(SaveData(), datetime(2026, 10, 20, 6, 29))
    assert q.current(datetime(2026, 10, 20, 6, 29, 30)) == "sleep"
    q._last_activity = datetime(2026, 10, 20, 6, 30)
    assert q.current(datetime(2026, 10, 20, 6, 30)) == "idle"


def test_woken_at_night_stays_awake_until_idle():
    p = PetState(SaveData(), NIGHT - sec(10))
    r = p.interact(NIGHT)
    assert keys(r) == ["wake"]
    assert p.current(NIGHT + timedelta(minutes=10)) == "idle"
    assert p.current(NIGHT + timedelta(minutes=16)) == "sleep"
    # 再次叫醒又会说起床台词
    assert keys(p.interact(NIGHT + timedelta(minutes=17))) == ["wake"]


def test_next_night_sleeps_again():
    p = PetState(SaveData(), NIGHT - sec(10))
    p.interact(NIGHT)
    next_night = NIGHT + timedelta(days=1)
    p._last_activity = next_night - sec(5)
    assert p.current(next_night) == "sleep"


# ---- 冷落 ----

def test_neglect_levels(pet):
    assert pet.current(T0 + timedelta(minutes=29)) in ("idle", "sleep")
    # 保持活跃（interact 不算被理会），只看底层档位
    def level(minutes):
        t = T0 + timedelta(minutes=minutes)
        pet._last_activity = t  # 避免睡眠遮住底层状态
        return pet.current(t)

    assert level(29) == "idle"
    assert level(30) == "neglect1"
    assert level(119) == "neglect1"
    assert level(120) == "neglect2"


def test_return_from_neglect2_says_special_line(pet):
    t = T0 + timedelta(hours=3)
    r = pet.click(t)
    assert "neglect_return" in keys(r)
    assert "wake" not in keys(r)  # 同时触发时只说回归台词
    assert "poke" not in keys(r)
    assert pet.current(t + sec(5)) == "idle"


def test_return_from_neglect1_is_silent_besides_wake(pet):
    t = T0 + timedelta(minutes=45)
    r = pet.pat(t)
    assert "neglect_return" not in keys(r)
    assert "wake" in keys(r)


def test_interact_does_not_reset_neglect(pet):
    t = T0 + timedelta(hours=3)
    pet.interact(t)
    assert pet.save.last_attended == T0
    pet._last_activity = t
    assert pet.current(t) == "neglect2"


def test_drag_counts_as_attended(pet):
    t = T0 + timedelta(minutes=45)
    pet.drag_start(t)
    assert pet.save.last_attended == t
    t2 = t + sec(5)
    pet.drag_end(t2)
    assert pet.save.last_attended == t2
    assert pet.current(t2 + sec(1)) == "idle"  # 冷落已重置


def test_drag_from_neglect2_says_return_line(pet):
    r = pet.drag_start(T0 + timedelta(hours=3))
    assert keys(r) == ["neglect_return"]


def test_drag_plain_says_drag_line(pet):
    assert keys(pet.drag_start(T0 + sec(5))) == ["drag"]


def test_drag_wakes_with_wake_line(pet):
    assert keys(pet.drag_start(T0 + timedelta(minutes=20))) == ["wake"]


def test_claude_event_resets_neglect(pet):
    t = T0 + timedelta(hours=3)
    r = pet.claude_event("prompt", None, t)
    assert "neglect_return" in keys(r)
    assert pet.save.last_attended == t


# ---- 连戳 / 戳到爆 ----

def click_n(pet, n, start, gap):
    out = []
    for i in range(n):
        out = pet.click(start + sec(i * gap))
    return out


def test_normal_click_pokes(pet):
    assert keys(pet.click(T0)) == ["poke"]


@pytest.mark.parametrize("count,roll,expected", [
    (1, 0, "poke"), (2, 0, "poke"),
    (3, 0, "stop"), (3, 0.599999, "stop"), (3, 0.60, "dizzy"),
    (3, 0.799999, "dizzy"), (3, 0.80, "poke"),
    (4, 0.60, "dizzy"), (4, 0.80, "poke"),
    (5, 0, "stop"), (5, 0.549999, "stop"), (5, 0.55, "dizzy"),
    (5, 0.949999, "dizzy"), (5, 0.95, "poke"), (6, 0.55, "dizzy"),
])
def test_poke_probability_boundaries(pet, monkeypatch, count, roll, expected):
    monkeypatch.setattr(pet._rng, "random", lambda: 0.99)
    click_n(pet, count - 1, T0, 0.2)
    monkeypatch.setattr(pet._rng, "random", lambda: roll)
    r = pet.click(T0 + sec((count - 1) * 0.2))
    assert keys(r) == [expected]
    if expected != "poke":
        assert pet._poke_count == 0
        assert keys(pet.click(T0 + sec(count * 0.2))) == ["poke"]


@pytest.mark.parametrize("gap,expected", [(1.5, "stop"), (1.500001, "poke")])
def test_poke_gap_inclusive_and_resets(pet, monkeypatch, gap, expected):
    monkeypatch.setattr(pet._rng, "random", lambda: 0)
    assert keys(click_n(pet, 3, T0, gap)) == [expected]


# ---- 摸头 ----

def test_pat_counts(pet):
    pet.pat(T0)
    pet.pat(T0 + sec(1))
    assert pet.save.affection == 2
    assert pet.save.stats["pats"] == 2
    assert pet.save.feedback_queue == []


def test_pat_never_adds_praise(pet):
    for i in range(8):
        pet.pat(T0 + sec(i))
    assert pet.save.feedback_queue == []
    assert pet.save.affection == 8  # 好感不受限
    pet.pat(T0 + sec(61))  # 窗口滑过之后又能加
    assert pet.save.feedback_queue == []


def test_take_feedback_clears(pet):
    pet.feedback_good(T0)
    pet.feedback_bad("  改得不对\n再看看  ", T0 + sec(1))
    items = pet.take_feedback()
    assert items == [{"kind": "good", "text": ""}, {"kind": "bad", "text": "改得不对 再看看"}]
    assert pet.take_feedback() == []
    assert pet.save.feedback_queue == []


def test_feedback_queue_keeps_latest_five_and_truncates_text(pet):
    for i in range(7):
        pet.feedback_bad(f"问题{i}", T0 + sec(i))
    assert [i["text"] for i in pet.save.feedback_queue] == [f"问题{i}" for i in range(2, 7)]
    pet.feedback_bad("长" * 500, T0)
    assert len(pet.save.feedback_queue[-1]["text"]) == 200


def test_paused_shows_stop_below_drag_and_expressions(pet):
    pet.paused = True
    assert pet.current(T0) == "stop"
    pet.claude_event("working", None, T0)
    assert pet.current(T0) == "stop"  # 暂停优先于 working
    pet.drag_start(T0)
    assert pet.current(T0) == "drag"
    pet.drag_end(T0)
    pet.paused = False
    assert pet.current(T0) == "working"


# ---- 统计与事件 ----

def test_stats_reset_on_new_day(pet):
    pet.pat(T0)
    assert pet.save.stats["pats"] == 1
    pet.pat(T0 + timedelta(days=1))
    assert pet.save.stats["pats"] == 1
    assert pet.save.stats["date"] == "2026-10-20"


def test_unknown_event_ignored(pet):
    t = T0 + timedelta(hours=3)
    assert pet.claude_event("bogus", None, t) == []
    assert pet.save.last_attended == T0  # 没有刷新“被理会”


def test_react_valid_and_invalid(pet):
    pet.claude_event("react", "proud", T0)
    assert pet.current(T0 + sec(2)) == "proud"
    assert pet.current(T0 + sec(3.1)) == "idle"
    pet.claude_event("react", "nonsense", T0 + sec(10))
    assert pet.current(T0 + sec(11)) == "idle"
    pet.claude_event("react", None, T0 + sec(12))
    assert pet.current(T0 + sec(13)) == "idle"


def test_notification_says_line(pet):
    assert "claude_waiting" in keys(pet.claude_event("notification", None, T0))


def test_first_run_and_attended_initialised(pet):
    assert pet.save.first_run == T0
    assert pet.save.last_attended == T0


def test_on_change_called():
    calls = []
    p = PetState(SaveData(), T0, on_change=calls.append)
    calls.clear()
    p.pat(T0 + sec(1))
    assert calls


# ---- debug 配置 ----

def test_debug_config_shortens_thresholds():
    p = PetState(SaveData(), T0, config=Config.debug())
    assert p.current(T0 + sec(19)) == "idle"
    assert p.current(T0 + sec(30)) == "neglect1"
    p._last_activity = T0 + sec(45)
    assert p.current(T0 + sec(45)) == "neglect2"
    assert p.current(T0 + sec(45 + 61)) == "sleep"


# ---- v0.2.1 ----

def test_tool_error_dizzy_for_2s_and_line(pet):
    r = pet.claude_event("tool_error", "Bash", T0)
    assert "tool_error" in keys(r)
    assert pet.current(T0) == "dizzy"
    assert pet.current(T0 + sec(1.9)) == "dizzy"
    assert pet.current(T0 + sec(2.1)) == "idle"


def test_nudge_after_5min_max_twice(pet):
    pet.claude_event("stop", None, T0)
    assert pet.tick(T0 + sec(299)) == []
    r = pet.tick(T0 + sec(300))
    assert [x.kind for x in r] == ["say", "nudge"] and r[0].key == "nudge"
    assert pet.tick(T0 + sec(301)) == []  # 下一次要再隔 5 分钟
    assert pet.tick(T0 + sec(600)) != []
    assert pet.tick(T0 + sec(900)) == []  # 最多 2 次


@pytest.mark.parametrize("etype", ["prompt", "working", "session_start"])
def test_nudge_reset_by_new_activity(pet, etype):
    pet.claude_event("stop", None, T0)
    pet.claude_event(etype, None, T0 + sec(100))
    assert pet.tick(T0 + sec(1000)) == []


def test_no_nudge_without_stop_or_when_asleep(pet):
    assert pet.tick(T0 + sec(1000)) == []
    p = PetState(SaveData(), T0, Config(nudge_after=timedelta(minutes=20)))
    p.claude_event("stop", None, T0)
    assert p.tick(T0 + timedelta(minutes=20)) == []  # 15 分钟无活动已睡着


def test_privacy_mode_roundtrip():
    d = SaveData()
    d.privacy_mode = True
    assert SaveData.from_dict(d.to_dict()).privacy_mode is True
    assert SaveData.from_dict({"privacy_mode": "x"}).privacy_mode is False


def test_nudge_cancelled_by_attention_and_wake(pet):
    pet.claude_event("stop", None, T0)
    pet.pat(T0 + sec(100))  # 用户理会了：不再催
    assert pet.tick(T0 + sec(1000)) == []
    p = PetState(SaveData(), T0)
    p.claude_event("stop", None, T0)
    p.interact(T0 + timedelta(minutes=16))  # 睡着后被唤醒：不会立刻冒出催促
    assert p.tick(T0 + timedelta(minutes=16, seconds=1)) == []


def test_manual_expression_expires_at_five_seconds(pet):
    pet.select_expression("sleep", T0)
    assert pet.current(T0 + sec(4.999)) == "sleep"
    assert pet.current(T0 + sec(5)) == "idle"
    pet.select_expression("drag", T0 + sec(5))
    assert pet.current(T0 + sec(5)) == "idle"  # 非菜单表情被忽略


@pytest.mark.parametrize("event", ["pat", "click", "working", "stop", "tool_error"])
def test_fixed_expression_survives_reactions_but_dialogue_and_stats_continue(pet, event):
    pet.select_expression("proud", T0)
    pet.fix_expression(True, T0)
    if event in ("pat", "click"):
        r = getattr(pet, event)(T0 + sec(1))
    else:
        r = pet.claude_event(event, None, T0 + sec(1))
    assert pet.current(T0 + sec(1)) == "proud"
    if event != "pat":
        assert r
    pet.drag_start(T0 + sec(2))
    assert pet.current(T0 + sec(2)) == "drag"
    pet.drag_end(T0 + sec(3), shaken=True)
    assert pet.current(T0 + sec(3)) == "proud"
    pet.select_expression("happy", T0 + sec(4))
    assert pet.save.fixed_expression == "happy"
    pet.fix_expression(False, T0 + sec(5))
    assert pet.save.fixed_expression is None
    assert pet.current(T0 + sec(5)) == ("working" if event == "working" else "idle")


def test_shaken_landing_dizzy_duration_and_dialogue(pet):
    pet.drag_start(T0)
    assert pet.current(T0 + sec(5)) == "drag"
    assert keys(pet.drag_end(T0 + sec(5), shaken=True)) == ["dizzy"]
    assert pet.current(T0 + sec(7.499)) == "dizzy"
    assert pet.current(T0 + sec(7.5)) == "idle"


def test_legacy_praise_migrates_once_without_resetting_other_data():
    raw = {"affection": 50, "pending_praise": 8}  # v1：混有摸头记录，丢弃
    data = SaveData.from_dict(raw)
    dirty = []
    p = PetState(data, T0, on_change=dirty.append)
    assert dirty and data.feedback_queue == [] and data.affection == 50
    assert data.schema_version == 3
    p.feedback_good(T0)
    q = PetState(SaveData.from_dict(data.to_dict()), T0)
    assert q.save.feedback_queue == [{"kind": "good", "text": ""}]


def test_v2_pending_praise_migrates_to_good_feedback():
    data = SaveData.from_dict({"schema_version": 2, "affection": 9, "pending_praise": 3})
    assert data.feedback_queue == [{"kind": "good", "text": ""}] * 3
    PetState(data, T0)
    assert data.schema_version == 3 and data.affection == 9
    again = SaveData.from_dict(data.to_dict())  # 已经是 v3：不会再迁移一遍
    assert again.feedback_queue == data.feedback_queue
    assert "pending_praise" not in data.to_dict()


def test_idle_expression_does_not_postpone_sleep_or_count_as_attention(pet):
    pet.idle_expression("happy", T0)
    assert pet.current(T0 + sec(1)) == "happy"
    assert pet.current(T0 + sec(2)) == "idle"
    assert pet.save.affection == 0 and pet.save.last_attended == T0
    assert pet.current(T0 + sec(900)) == "sleep"


@pytest.mark.parametrize("block", ["working", "fixed", "sleep", "drag", "manual", "reaction"])
def test_idle_eligibility_uses_real_state_even_when_expression_is_different(pet, block):
    if block == "working":
        pet.claude_event("working", None, T0)
        pet.pat(T0)  # 画面是 happy，Claude 实际仍在工作
    elif block == "fixed":
        pet.fix_expression(True, T0)
    elif block == "sleep":
        assert not pet.can_idle(T0 + sec(900))
        return
    elif block == "drag":
        pet.drag_start(T0)
    elif block == "manual":
        pet.select_expression("idle", T0)
    else:
        pet.pat(T0)
    assert not pet.can_idle(T0)
