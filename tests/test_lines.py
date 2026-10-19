import random

from shion.lines import Lines

# 状态机和界面层会用到的台词类别（见 progress.md 的“第 3 步接口”）
NEEDED = {
    "poke", "stop", "dizzy", "drag", "wake", "neglect_return", "praise_menu",
    "claude_working", "claude_done", "pat", "greeting", "claude_waiting",
}


def test_zh_json_has_every_key_the_state_machine_uses():
    assert NEEDED <= Lines().keys()


def test_pick_never_repeats_consecutively():
    lines = Lines(rng=random.Random(5))
    prev = None
    for _ in range(200):
        cur = lines.pick("poke")
        assert cur != prev
        prev = cur


def test_single_line_category_and_unknown_key():
    lines = Lines()
    assert lines.pick("praise_menu") == lines.pick("praise_menu")  # 只有一句时允许重复
    assert lines.pick("no_such_key") is None


def test_missing_file_is_not_fatal(tmp_path):
    assert Lines(tmp_path / "nope.json").pick("poke") is None
