"""好感度规则、迁移、额度与损坏配置回退；时间和随机数均可控。"""
import copy
import json
import math
from dataclasses import replace
from datetime import timedelta

import pytest

from shion.affection import AFFECTION_PATH, load_rules
from shion.lines import Lines, LINES_DIR
from shion.menu_content import MenuContent
from shion.state import PetState, SaveData, SAVE_VERSION, save, load
from tests.test_controller import T0


@pytest.fixture
def rules():
    result = load_rules()
    assert result is not None
    return result


def make(rules, points=0, data=None, now=T0):
    return PetState(data if data is not None else SaveData(affection=points), now, affection=rules)


@pytest.mark.parametrize("points,level", [(0, 1), (49, 1), (50, 2), (199, 2), (200, 3),
                                          (499, 3), (500, 4), (999, 4), (1000, 5), (1000000, 5)])
def test_thresholds(rules, points, level):
    assert rules.level(points) == level


@pytest.mark.parametrize("version", [1, 2, 3, 4, SAVE_VERSION])
@pytest.mark.parametrize("points", [0, 49, 50, 200, 500, 1000, 4000])
def test_migration_recalculates_level_without_replaying(rules, version, points):
    data = SaveData.from_dict({"schema_version": version, "affection": points, "affection_level": 1})
    state = make(rules, data=data)
    assert data.affection_level == rules.level(points)
    assert data.schema_version == SAVE_VERSION and data.affection == points
    assert not any(r.kind == "level_up" for r in state.tick(T0))
    assert state.interact(T0) == []


def test_daily_caps_restart_and_new_date(rules, tmp_path):
    state = make(rules)
    for _ in range(25):
        state.pat(T0)
    assert state.save.affection == 20 and state.save.stats["pats"] == 25
    state.gain_affection("open", T0)
    state.gain_affection("open", T0)
    for ident in ("a", "a", "b", "b"):
        state.gain_affection("talk", T0, ident)
    assert state.save.affection == 24
    for i in range(5):
        now = T0 + timedelta(seconds=i * 3)
        assert state.start_snack(now)
        assert state.tick(now + timedelta(seconds=1.999)) == []
        state.tick(now + timedelta(seconds=2))
    assert state.save.affection == 34
    assert not state.start_snack(T0 + timedelta(seconds=20))
    assert state.affection_remaining(T0, ("a", "b")) == 0
    path = tmp_path / "state.json"
    save(path, state.save)
    again = make(rules, data=load(path))
    assert again.affection_remaining(T0, ("a", "b")) == 0
    again.pat(T0)
    again.gain_affection("open", T0)
    again.gain_affection("talk", T0, "a")
    assert again.save.affection == 34
    tomorrow = T0 + timedelta(days=1)
    again.tick(tomorrow)
    assert again.affection_remaining(tomorrow, ("a", "b")) == 34
    assert again.save.stats["pats"] == 0 and again.save.snacks["count"] == 0
    again.gain_affection("open", tomorrow)
    again.gain_affection("talk", tomorrow, "a")
    again.pat(tomorrow)
    assert again.save.affection == 38


def test_migrating_today_counts_existing_pats_and_snacks(rules):
    data = SaveData.from_dict({"schema_version": 4, "affection": 101,
        "stats": {"date": T0.date().isoformat(), "pats": 100, "claude_tasks": 7},
        "snacks": {"date": T0.date().isoformat(), "count": 4}})
    state = make(rules, data=data)
    assert state.affection_remaining(T0, []) == 4  # 零食一次 +2，首次打开 +2
    state.pat(T0)
    assert state.save.affection == 101 and state.save.stats["pats"] == 101
    assert state.start_snack(T0)
    state.tick(T0 + timedelta(seconds=2))
    assert state.save.affection == 103


def test_migrating_old_date_does_not_consume_today(rules):
    data = SaveData.from_dict({"stats": {"date": "2020-01-01", "pats": 200},
                               "snacks": {"date": "2020-01-01", "count": 5}})
    state = make(rules, data=data)
    assert state.affection_remaining(T0, []) == 32


def test_midnight_snack_counts_only_on_completion_and_cancel_never_rewards(rules):
    now = T0.replace(hour=23, minute=59, second=59)
    state = make(rules, now=now)
    assert state.start_snack(now)
    state.tick(now + timedelta(seconds=2))
    assert state.save.affection == 2
    assert state.save.affection_daily["snack"] == 1
    assert state.save.affection_daily["date"] == (now + timedelta(days=1)).date().isoformat()
    state.tick(now + timedelta(seconds=30))
    assert state.save.affection == 2
    assert state.start_snack(now + timedelta(seconds=31))
    state.cancel_snack()
    state.tick(now + timedelta(seconds=40))
    assert state.save.affection == 2 and state.save.snacks["count"] == 1


@pytest.mark.parametrize("source,points", [("pat", 49), ("snack", 48), ("talk", 199), ("open", 499)])
def test_each_source_upgrades_once_and_survives_restart(rules, tmp_path, source, points):
    state = make(rules, points)
    if source == "pat":
        reactions = state.pat(T0)
    elif source == "snack":
        state.start_snack(T0)
        reactions = state.tick(T0 + timedelta(seconds=2))
    else:
        reactions = state.gain_affection(source, T0, "a")
    upgrades = [r for r in reactions if r.kind == "level_up"]
    assert len(upgrades) == 1 and int(upgrades[0].key) == rules.level(state.save.affection)
    assert not any(r.kind == "level_up" for r in state.tick(T0 + timedelta(seconds=10)))
    path = tmp_path / "state.json"
    save(path, state.save)
    again = make(rules, data=load(path))
    assert not any(r.kind == "level_up" for r in again.tick(T0))


def test_one_atomic_gain_crossing_several_levels_only_announces_final_level(rules):
    changed = copy.deepcopy(rules.daily)
    changed["open"]["amount"] = 1100
    state = make(replace(rules, daily=changed))
    reactions = state.gain_affection("open", T0)
    assert [(r.kind, r.key) for r in reactions] == [("level_up", "5")]
    assert state.gain_affection("open", T0) == []


def test_feedback_is_not_a_fifth_reward_source_and_no_affection_decay(rules):
    state = make(rules, 500)
    state.feedback_good(T0)
    assert state.save.affection == 500 and state.save.feedback_queue
    state.tick(T0 + timedelta(days=100))
    assert state.save.affection == 500 and state.affection_level == 4


@pytest.mark.parametrize("level", range(1, 6))
@pytest.mark.parametrize("late", [False, True])
def test_probability_bounds_and_ratio(rules, level, late):
    base = (0.55, 0.4) if late else (0.6, 0.2)
    stop, dizzy = rules.probabilities(level, *base)
    assert 0 <= stop <= 1 and 0 <= dizzy <= 1 and stop + dizzy <= 1
    assert math.isclose(stop / dizzy, base[0] / base[1])
    assert rules.probabilities(5, *base)[0] < rules.probabilities(1, *base)[0]


@pytest.mark.parametrize("factor", [0, 0.6, 1.2, 100])
def test_scaled_random_cutoffs(rules, factor):
    changed = replace(rules, levels=tuple(replace(item, poke_factor=factor) for item in rules.levels))
    stop, dizzy = changed.probabilities(1, 0.6, 0.2)
    for roll, expected in ((max(0, stop - 1e-8), "stop" if stop else "poke"),
                           (stop, "dizzy" if dizzy else "poke"),
                           (round(stop + dizzy, 12), "poke")):
        state = make(changed)
        state._rng = type("Random", (), {"random": lambda self: roll})()
        reactions = []
        for _ in range(3):
            reactions = state.click(T0)
        assert reactions[-1].key == expected


@pytest.mark.parametrize("level", [None, 1, 2, 3, 4, 5])
def test_menu_unlocks(level):
    content = MenuContent()
    ids = {i.id for i in content.visible("talks", level)}
    snacks = {i.id for i in content.visible("snacks", level)}
    assert ("stay_with_me" in ids) == (level is None or level >= 2)
    assert ("listen_to_me" in ids) == (level is None or level >= 3)
    assert ("stay_together" in ids) == (level is None or level >= 5)
    assert ("shared_chocolate" in snacks) == (level is None or level >= 4)


@pytest.mark.parametrize("invalid", [0, -1, 6, True, "2", None, [], {}])
def test_bad_min_level_menu_entries_are_skipped(tmp_path, invalid):
    item = {"id": "bad", "name": {"zh": "坏"}, "min_level": invalid, "responses": [{"text": {"zh": "坏"}}]}
    (tmp_path / "talks.json").write_text(json.dumps({"schema_version": 1, "items": [item]}), encoding="utf-8")
    assert not MenuContent(tmp_path).talks


def test_min_level_lines_filter_and_legacy_strings(tmp_path):
    raw = {"lines": {"test": ["普通", {"text": "亲近", "min_level": 3},
                                      {"text": "坏", "min_level": True}]}}
    (tmp_path / "zh.json").write_text(json.dumps(raw), encoding="utf-8")
    lines = Lines(directory=tmp_path)
    assert {lines.pick("test", 1) for _ in range(10)} == {"普通"}
    assert {lines.pick("test", 3) for _ in range(10)} == {"普通", "亲近"}
    assert {lines.pick("test", None) for _ in range(10)} == {"普通", "亲近"}


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_all_new_content_is_native_trilingual_and_level_specific(rules, lang):
    raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    for level in range(1, 6):
        assert rules.levels[level - 1].name[lang] and rules.levels[level - 1].upgrade[lang]
        for key in ("pat", "neglect_return", "idle_talk"):
            pool = raw["lines"][f"{key}_level_{level}"]
            assert 2 <= len(pool) <= 3
            assert all(item["min_level"] == level and item["text"] for item in pool)
            assert Lines(lang).pick(f"{key}_level_{level}", level - 1) is None
    assert all(item["min_level"] == 5 for item in raw["lines"]["idle_thanks"])


@pytest.mark.parametrize("bad", [None, [], {}, {"schema_version": True}, {"schema_version": 2}, "broken", "missing"])
def test_invalid_configuration_restores_legacy_rewards_and_no_levels(tmp_path, bad):
    path = tmp_path / "affection.json"
    if bad != "missing":
        path.write_text("{broken" if bad == "broken" else json.dumps(bad), encoding="utf-8")
    assert load_rules(path) is None
    state = make(load_rules(path))
    for _ in range(25):
        state.pat(T0)
    state.feedback_good(T0)
    state.gain_affection("open", T0)
    state.gain_affection("talk", T0, "a")
    assert state.save.affection == 28 and state.affection_level is None


@pytest.mark.parametrize("field,value", [("threshold", -1), ("threshold", True), ("threshold", 0),
    ("name", {"zh": "缺英文"}), ("upgrade", []), ("level", 4),
    ("poke_factor", -1), ("poke_factor", float("nan")), ("poke_factor", float("inf")), ("poke_factor", True)])
def test_malformed_level_config_falls_back(tmp_path, field, value):
    raw = json.loads(AFFECTION_PATH.read_text(encoding="utf-8"))
    raw["levels"][1][field] = value
    path = tmp_path / "affection.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_rules(path) is None


@pytest.mark.parametrize("section,field,value", [("pat", "amount", True), ("pat", "limit", 0),
    ("snack", "amount", -2), ("snack", "limit", "5"), ("talk", "limit", 2), ("open", "limit", 2)])
def test_malformed_daily_config_falls_back(tmp_path, section, field, value):
    raw = json.loads(AFFECTION_PATH.read_text(encoding="utf-8"))
    raw["daily"][section][field] = value
    path = tmp_path / "affection.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_rules(path) is None


def test_corrupt_saved_fields_are_sanitized_and_recalculated(rules):
    data = SaveData.from_dict({"affection": 500, "affection_level": True,
        "affection_daily": {"date": T0.date().isoformat(), "pat": True, "snack": -1,
                            "open": "yes", "talks": ["a", "a", "", 3, {}]}})
    state = make(rules, data=data)
    assert state.affection_level == data.affection_level == 4
    assert data.affection_daily == {"date": T0.date().isoformat(), "pat": 0, "snack": 0, "open": 0, "talks": ["a"]}


def test_disabled_then_repaired_config_retains_points_and_no_upgrade_replay(rules):
    state = make(rules, 999)
    data = SaveData.from_dict(state.save.to_dict())
    disabled = make(None, data=data)
    disabled.pat(T0)
    assert data.affection == 1000 and data.affection_level == 4
    repaired = make(rules, data=SaveData.from_dict(data.to_dict()))
    assert repaired.save.affection_level == 5
    assert repaired.save.affection_daily["pat"] == 1
    assert repaired.tick(T0) == []
