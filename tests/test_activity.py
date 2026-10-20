from datetime import datetime, timedelta

from shion.activity import ActivityLog, Entry, describe, make_entry, parse_working

T0 = datetime(2026, 10, 19, 12, 0)


def ui(key, **kw):
    return f"{key}|{kw.get('target', kw.get('text', ''))}"


def test_parse_working():
    assert parse_working('{"tool":"read","target":"a.py"}') == ("read", "a.py")
    assert parse_working('{"tool":"nope"}') == ("other", "")
    assert parse_working("not json") is None and parse_working(None) is None
    assert parse_working("[1]") is None


def test_make_entry_filters_events():
    assert make_entry("prompt", None, T0) is None
    assert make_entry("notification", "x", T0) is None
    assert make_entry("stop", "私密回复", T0).target == ""
    assert make_entry("plan_ready", "私密计划", T0) is None
    assert make_entry("working", '{"tool":"edit","target":"a.py"}', T0).tool == "edit"
    assert make_entry("working", None, T0).tool == "other"


def test_max_20_and_recent_5_newest_first():
    log = ActivityLog()
    for i in range(25):
        log.add(Entry(T0 + timedelta(minutes=i), "stop", target=str(i)))
    assert len(log) == 20
    assert [e.target for e in log.recent()] == ["24", "23", "22", "21", "20"]
    log.add(None)
    assert len(log) == 20


def test_describe_respects_privacy():
    e = Entry(T0, "working", "read", "secret.py")
    assert describe(e, ui, False) == "act_read|secret.py"
    assert describe(e, ui, True) == "act_private|"
    s = Entry(T0, "stop", target="我的密码")
    assert describe(s, ui, False) == "act_done|"
    assert describe(s, ui, True) == "act_done|"
    t = Entry(T0, "tool_error", target="Bash")
    assert describe(t, ui, False) == "act_error|Bash" and describe(t, ui, True) == "act_error_plain|"
    assert describe(Entry(T0, "working", "read", ""), ui, False) == "act_other|"
    assert describe(Entry(T0, "session_start"), ui, False) == "act_start|"


def test_recent_lines_format():
    log = ActivityLog()
    log.add(Entry(T0, "working", "edit", "a.py"))
    assert log.recent_lines(ui, False) == ["12:00 act_edit|a.py"]
    assert "a.py" not in log.recent_lines(ui, True)[0]
