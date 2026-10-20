"""素材处理脚本只读回归；不覆盖仓库里的生成帧。"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def sheets(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "tools"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("tested_process_sheets", directory / "process_sheets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_touching_frames_are_split_and_small_details_follow_nearest_frame(sheets):
    a = np.zeros((150, 880, 4), dtype=np.uint8)
    for i in range(8):
        x = 5 + i * 110
        a[30:130, x:x + 100] = 255
    # 将第二、第三个人物用细桥连起来；其他独立帧提供宽度基准。
    a[78:82, 210:225] = 255
    a[10:15, 30:35] = 255
    frames = sheets.split_frames(Image.fromarray(a))
    assert len(frames) == 8
    assert all(90 <= image.width <= 115 for image, _ in frames)
    assert frames[0][0].height == 120  # 小碎块归入最近一帧
    assert all(bottom == 130 for _, bottom in frames)


def test_wrong_frame_count_stops_before_writing_outputs(sheets, monkeypatch, tmp_path):
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    monkeypatch.setattr(sheets.ps, "load_clean", lambda _: image)
    monkeypatch.setattr(sheets.ps, "OUT", tmp_path)
    with pytest.raises(SystemExit, match="8"):
        sheets.main()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("group,count", [("walk", 8), ("jump", 4), ("drag", 4), ("turn", 8), ("tickle", 3), ("cheek", 3)])
def test_current_raw_sheets_split_to_expected_count_and_outputs_decode(sheets, group, count):
    assert sheets.EXPECTED[f"{group}_sheet"] == count
    frames = sheets.split_frames(sheets.ps.load_clean(sheets.ps.RAW / f"{group}_sheet.png"))
    assert len(frames) == count
    for i in range(1, count + 1):
        with Image.open(sheets.ps.OUT / f"{group}_{i}.png") as image:
            image.load()
            assert image.size == sheets.ps.CANVAS and image.mode == "RGBA"
