import json
from datetime import datetime, timedelta

from shion.state import SaveData, SaveScheduler, load, save

T0 = datetime(2026, 10, 19, 12, 0, 0)


def test_round_trip(tmp_path):
    p = tmp_path / "state.json"
    d = SaveData(
        first_run=T0,
        affection=7,
        last_attended=T0 + timedelta(minutes=3),
        pending_praise=2,
        stats={"date": "2026-10-19", "pats": 4, "claude_tasks": 1},
        window={"x": 10, "y": 20, "height": 320},
        bubble_muted=True,
        inject_praise=False,
        fixed_expression="dizzy",
        activity_level="lively",
    )
    save(p, d)
    assert load(p) == d


def test_behavior_settings_reject_invalid_values():
    for value in (None, "drag", "blink", "neglect1", [], {}, 5, True):
        d = SaveData.from_dict({"fixed_expression": value, "activity_level": value})
        assert d.fixed_expression is None and d.activity_level == "normal"


def test_missing_file_gives_defaults(tmp_path):
    d = load(tmp_path / "nope.json")
    assert d == SaveData()
    assert d.affection == 0 and d.inject_praise is True
    assert d.window["height"] == 200


def test_corrupt_json_recovers_and_backs_up(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ not json", encoding="utf-8")
    assert load(p) == SaveData()
    assert not p.exists()
    assert (tmp_path / "state.json.bad").read_text(encoding="utf-8") == "{ not json"


def test_non_object_json_treated_as_corrupt(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load(p) == SaveData()
    assert (tmp_path / "state.json.bad").exists()


def test_empty_file_treated_as_corrupt(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("", encoding="utf-8")
    assert load(p) == SaveData()


def test_missing_and_wrong_type_fields_fall_back(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({
            "affection": "lots",
            "pending_praise": -3,
            "first_run": "yesterday",
            "bubble_muted": "yes",
            "stats": {"date": 5, "pats": "x"},
            "window": {"x": "left", "height": 0},
            "unknown_field": 1,
        }),
        encoding="utf-8",
    )
    d = load(p)
    assert d.affection == 0
    assert d.pending_praise == 0
    assert d.first_run is None
    assert d.bubble_muted is False
    assert d.stats == {"date": "", "pats": 0, "claude_tasks": 0}
    assert d.window["x"] is None and d.window["height"] == 120  # 0 被限制到下限


def test_partial_file_keeps_valid_fields(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"affection": 12, "inject_praise": False}), encoding="utf-8")
    d = load(p)
    assert d.affection == 12
    assert d.inject_praise is False
    assert d.window["height"] == 200


def test_atomic_save_leaves_no_tmp_and_creates_dirs(tmp_path):
    p = tmp_path / "sub" / "state.json"
    save(p, SaveData(affection=1))
    assert p.exists()
    assert not (tmp_path / "sub" / "state.json.tmp").exists()
    save(p, SaveData(affection=2))
    assert load(p).affection == 2
    assert [f.name for f in p.parent.iterdir()] == ["state.json"]


def test_scheduler_debounce(tmp_path):
    p = tmp_path / "state.json"
    data = SaveData(affection=1)
    s = SaveScheduler(p, data)
    assert not s.due(T0)  # 没变化就不写

    s.mark_dirty(T0)
    assert not s.poll(T0 + timedelta(seconds=1.9))
    assert not p.exists()

    s.mark_dirty(T0 + timedelta(seconds=1.9))  # 又变化：重新计时
    assert not s.poll(T0 + timedelta(seconds=3.0))
    assert s.poll(T0 + timedelta(seconds=3.9))
    assert load(p).affection == 1
    assert not s.dirty
    assert not s.poll(T0 + timedelta(seconds=10))  # 写过就不再写


def test_scheduler_flush_writes_immediately(tmp_path):
    p = tmp_path / "state.json"
    s = SaveScheduler(p, SaveData(affection=5))
    s.mark_dirty(T0)
    s.flush()
    assert load(p).affection == 5


def test_scheduler_flush_noop_when_clean(tmp_path):
    p = tmp_path / "state.json"
    SaveScheduler(p, SaveData()).flush()
    assert not p.exists()


# ---- 审查修复 ----
def test_height_is_clamped_to_sane_range():
    assert SaveData.from_dict({"window": {"height": 99999}}).window["height"] == 600
    assert SaveData.from_dict({"window": {"height": 1}}).window["height"] == 120
    assert SaveData.from_dict({"window": {"height": 320}}).window["height"] == 320


def make_broken(tmp_path):
    """存档路径的父目录其实是个文件：写盘必然抛 OSError。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    return blocker / "state.json"


def test_flush_failure_does_not_raise_and_keeps_dirty(tmp_path):
    s = SaveScheduler(make_broken(tmp_path), SaveData())
    s.mark_dirty(T0)
    assert s.flush(T0 + timedelta(seconds=3)) is False
    assert s.dirty is True
    assert s.flush() is False  # 退出时的无参 flush 也不抛


def test_failed_save_is_retried_only_after_backoff_then_succeeds(tmp_path):
    path = make_broken(tmp_path)
    s = SaveScheduler(path, SaveData())
    s.mark_dirty(T0)
    t = T0 + timedelta(seconds=3)
    assert s.poll(t) is False  # 到点，写失败
    assert not s.due(t + timedelta(seconds=10))  # 退避中：不会每个 tick 都重试
    assert not s.poll(t + timedelta(seconds=29))
    # 目录恢复可写（把挡路的文件换成目录）
    path.parent.unlink()
    path.parent.mkdir()
    assert s.poll(t + timedelta(seconds=31)) is True
    assert s.dirty is False and path.exists()


def test_take_praise_uses_given_time_for_debounce():
    from shion.state import PetState

    dirty = []
    st = PetState(SaveData(pending_praise=2), T0, on_change=dirty.append)
    dirty.clear()
    later = T0 + timedelta(hours=1)
    assert st.take_praise(later) == 2
    assert dirty == [later]


def test_language_roundtrip_and_invalid_values(tmp_path):
    p = tmp_path / "state.json"
    assert load(p).language is None  # 没选过
    p.write_text(json.dumps({"language": "ja"}), encoding="utf-8")
    assert load(p).language == "ja"
    for bad in (5, "", None, ["zh"]):
        p.write_text(json.dumps({"language": bad}), encoding="utf-8")
        assert load(p).language is None
    save(p, SaveData(language="en"))
    assert load(p).language == "en"
