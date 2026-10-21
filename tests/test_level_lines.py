"""混合等级池的范围、分池权重和连续去重。"""
import json
import random
from collections import Counter

import pytest

from shion.lines import CURRENT_LEVEL_WEIGHT, LEVELED_KEYS, Lines


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("key", sorted(LEVELED_KEYS))
@pytest.mark.parametrize("level", range(1, 6))
def test_mixed_selection_only_uses_all_unlocked_pools(lang, key, level):
    lines = Lines(lang, rng=random.Random(21))
    expected = set(lines._pool(key, level))
    for i in range(1, level + 1):
        expected.update(lines._pool(f"{key}_level_{i}", level))
    selected = [lines.pick_for_level(key, level) for _ in range(500)]
    assert set(selected) == expected
    assert all(a != b for a, b in zip(selected, selected[1:]))


@pytest.mark.parametrize("level", range(1, 6))
def test_weights_are_per_pool_even_with_unequal_pool_sizes(tmp_path, level):
    pools = {"pat": [f"generic:{i}" for i in range(30)]}
    for i in range(1, 6):
        pools[f"pat_level_{i}"] = [f"{i}:{j}" for j in range(i * 3)]
    (tmp_path / "zh.json").write_text(json.dumps({"lines": pools}), encoding="utf-8")
    lines = Lines(rng=random.Random(42), directory=tmp_path)
    n = 30000
    counts = Counter(lines.pick_for_level("pat", level).split(":")[0] for _ in range(n))
    assert set(counts) == {"generic", *(str(i) for i in range(1, level + 1))}
    assert abs(counts[str(level)] / n - CURRENT_LEVEL_WEIGHT) < .015
    for pool in {"generic", *(str(i) for i in range(1, level))}:
        assert abs(counts[pool] / n - (1 - CURRENT_LEVEL_WEIGHT) / level) < .015


def test_empty_current_pool_renormalizes_other_pools_and_filters_min_level(tmp_path):
    raw = {"lines": {"pat": ["generic-a", "generic-b"],
        "pat_level_1": ["lower-a", "lower-b"], "pat_level_2": [],
        "pat_level_3": [{"text": "locked", "min_level": 5}]}}
    (tmp_path / "zh.json").write_text(json.dumps(raw), encoding="utf-8")
    lines = Lines(rng=random.Random(3), directory=tmp_path)
    counts = Counter(lines.pick_for_level("pat", 3).split("-")[0] for _ in range(10000))
    assert set(counts) == {"generic", "lower"}
    assert abs(counts["generic"] / 10000 - .5) < .025


def test_repeat_removal_renormalizes_singleton_pools_and_shares_base_history(tmp_path):
    raw = {"lines": {"pat": ["common"], "pat_level_1": ["current"]}}
    (tmp_path / "zh.json").write_text(json.dumps(raw), encoding="utf-8")
    lines = Lines(rng=random.Random(3), directory=tmp_path)
    assert lines.pick("pat") == "common"
    assert [lines.pick_for_level("pat", 1) for _ in range(4)] == ["current", "common", "current", "common"]
    lines._lines.pop("pat_level_1")
    assert lines.pick_for_level("pat", 1) == "common"
    lines._lines.pop("pat")
    assert lines.pick_for_level("pat", 1) is None


def test_no_level_keeps_generic_pool():
    lines = Lines(rng=random.Random(5))
    assert {lines.pick_for_level("pat", None) for _ in range(200)} == set(lines._pool("pat", None))
