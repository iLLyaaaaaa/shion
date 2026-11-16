"""tools/v3_perf 的场景名解析（纯逻辑，不开窗口）：旧场景含义不变，S9 新增 state:<名>+<驱动> 与 switch。"""
import pytest

from tools import v3_perf


@pytest.mark.parametrize("scenario, expected", [
    ("idle", ("idle", "idle")),
    ("working", ("working", "working")),
    ("pinch", ("idle", "pinch")),
    ("lift", ("idle", "lift")),
    ("state:slump", ("slump", None)),
    ("state:bed", ("bed", None)),
    ("state:bed+knock", ("bed", "knock")),
    ("state:desk+pat", ("desk", "pat")),
    ("switch", ("idle", "switch")),
])
def test_parse_scenario(scenario, expected):
    assert v3_perf.parse_scenario(scenario) == expected


def test_switch_cycle_visits_every_scene_state():
    assert v3_perf.SWITCH_CYCLE[0] == "idle"
    assert {"bed", "desk", "collapse"} <= set(v3_perf.SWITCH_CYCLE)


def test_knock_drive_is_known_to_the_v3_driver():
    """+knock / +pat 必须是 drive_v3 认识的名字，否则场景什么也不驱动。"""
    import inspect
    source = inspect.getsource(v3_perf.drive_v3)
    for name in ("knock", "pat", "switch"):
        assert f"'{name}'" in source
