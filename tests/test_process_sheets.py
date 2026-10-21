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


@pytest.mark.parametrize("group,count", [("walk", 8), ("jump", 4), ("drag", 4), ("turn", 8), ("tickle", 3), ("cheek", 3), ("bed", 2), ("desk", 3)])
def test_current_raw_sheets_split_to_expected_count_and_outputs_decode(sheets, group, count):
    assert sheets.EXPECTED[f"{group}_sheet"] == count
    frames = sheets.split_frames(sheets.ps.load_clean(sheets.ps.RAW / f"{group}_sheet.png"))
    assert len(frames) == count
    for i in range(1, count + 1):
        with Image.open(sheets.ps.OUT / f"{group}_{i}.png") as image:
            image.load()
            assert image.size == (sheets.WIDE.get(f"{group}_sheet", sheets.ps.CANVAS[0]), sheets.ps.CANVAS[1])
            assert image.mode == "RGBA"


@pytest.mark.parametrize("group,width", [("bed", 640), ("desk", 448)])
def test_props_are_centered_as_a_whole_and_share_bottom_baseline(sheets, group, width):
    for i in range(1, sheets.EXPECTED[group + "_sheet"] + 1):
        with Image.open(sheets.ps.OUT / f"{group}_{i}.png") as image:
            left, top, right, bottom = image.getbbox()
            assert abs((left + right) / 2 - width / 2) <= 2
            assert bottom == sheets.ps.CANVAS[1] - sheets.ps.BOTTOM


def test_largest_component_and_z_use_area_not_position_or_bbox(sheets):
    a = np.zeros((100, 120, 4), dtype=np.uint8)
    a[50:90, 0:40] = (20, 30, 40, 255)
    a[0:10, 90:100] = (50, 60, 70, 255)
    a[20:25, 60:65] = (80, 90, 100, 255)
    # 细长块边界很大，面积仍小于最大的 Z。
    a[5:85, 110:111] = 255
    image = Image.fromarray(a)
    assert sheets.ps.largest_component(image).size == (40, 40)
    z = sheets.ps.largest_component(image, rank=1)
    assert z.size == (10, 10) and z.getpixel((0, 0)) == (50, 60, 70, 255)
    with pytest.raises(ValueError):
        sheets.ps.largest_component(Image.new("RGBA", (10, 10)))


def test_selective_sleep_and_bed_generation_only_writes_requested_outputs(sheets, monkeypatch, tmp_path):
    monkeypatch.setattr(sheets.ps, "OUT", tmp_path)
    sentinel = tmp_path / "idle.png"
    sentinel.write_bytes(b"must not change")
    sheets.ps.main(["sleep"])
    sheets.main(["bed"])
    assert {p.name for p in tmp_path.iterdir()} == {"idle.png", "sleep.png", "fx_z.png", "bed_1.png", "bed_2.png"}
    assert sentinel.read_bytes() == b"must not change"
    # 同原图像素清理后的第二大连通块逐像素一致。
    expected = sheets.ps.largest_component(sheets.ps.load_clean(sheets.ps.RAW / "sleep.png"), rank=1)
    assert np.array_equal(np.array(expected), np.array(Image.open(tmp_path / "fx_z.png")))
    for name in ("sleep", "bed_1", "bed_2"):
        from scipy import ndimage as nd
        image = Image.open(tmp_path / f"{name}.png")
        labels, _ = nd.label(np.array(image)[..., 3] > 40)
        assert sum(area > 20 for area in np.bincount(labels.ravel())[1:]) == 1
        assert (tmp_path / f"{name}.png").read_bytes() == (sheets.ps.ROOT / "assets/sprites" / f"{name}.png").read_bytes()
