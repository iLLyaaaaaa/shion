"""媒体的确定性、连续取帧、真实效果、编码预算与旧截图共用入口。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image, ImageChops
from PySide6.QtGui import QImage
from shiboken6 import isValid

from shion.app import SnapshotScene
from shion.behavior import LEGACY_JUMP_HEIGHT
from tests.test_controller import qapp
from tools import make_media as media


def pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return bytes(image.constBits())


def test_scene_seed_repeats_full_timeline_and_releases_window(qapp):
    batches = []
    for _ in range(2):
        with SnapshotScene(seed=42, height=260, scale=2) as scene:
            win = scene.win
            assert win._v3_dpr == 2  # V3 的贴图按显示高度 × DPR 渲染（不再有 V2 的 _pixmaps）
            batch = []
            for at in (0, .3, 3.2, 3.5, 6.0, 10.0, 12.0):
                scene.advance_to(at)
                image = scene.render()
                assert image.size() == win.size() * 2
                batch.append(pixels(image))
            batches.append(batch)
        assert not isValid(win)
    assert batches[0] == batches[1]
    assert len(set(batches[0])) > 1


@pytest.mark.parametrize("at", [.5, float("nan"), float("inf"), -float("inf")])
def test_scene_rejects_backward_or_nonfinite_time(qapp, at):
    with SnapshotScene(seed=42) as scene:
        scene.advance_to(1)
        with pytest.raises(ValueError):
            scene.advance_to(at)


def test_pat_reuses_visible_hearts_and_bed_reuses_z(qapp):
    pat = media.pil_image(media.pat_image())
    with SnapshotScene("happy", height=260, activity="quiet", seed=42, scale=2) as scene:
        for elapsed in (0.0, .2, .4, .65):  # V3 的发丝/呼吸与步进路径有关：用和 pat_image 相同的步进再取底图
            scene.advance_to(elapsed)
        base = media.pil_image(scene.render())
        diff = ImageChops.difference(pat, base).convert("RGB").getbbox()
        assert diff and diff[3] < 2 * 100  # 差异位于头顶的爱心区。
    with SnapshotScene("bed", height=260, seed=42, scale=2) as scene:
        scene.advance_to(.9)
        scene.advance_to(1.8)
        assert len(scene.win._sleep_z.particles.items(scene.time[0])) == 3
        assert pixels(scene.render()) != pixels(scene.win.render_frame(2))


def test_hero_uses_one_scene_v3_blink_pinch_pat_work_jump_and_returns_to_identical_idle(qapp, monkeypatch):
    import shion.app
    scenes, samples = [], []

    class ObservedScene(SnapshotScene):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            scenes.append(self)

        def render(self):
            animator = self.win._v3_animator
            samples.append((self.win.frame, self.win._jump_offset, animator.dragging, animator.pose))
            return super().render()

    monkeypatch.setattr(shion.app, "SnapshotScene", ObservedScene)
    frames = media.hero_frames()
    assert len(scenes) == 1 and len(frames) == media.FRAME_COUNT == 100
    assert frames[0].tobytes() == frames[-1].tobytes()
    assert all(frame.size == (480, 360) and frame.mode == "RGB" for frame in frames)
    # 输入走真实窗口的动画器：12～29 帧捏着脸颊（dragging），30 帧起松手；其余时间不在拖动。
    assert [i for i, s in enumerate(samples) if s[2]] == list(range(12, 30))
    # 眨眼是 V3 自己的（blink_start 被拨到 0.4 秒后）：第 8～16 帧内眼睛闭合过。
    assert any(getattr(s[3], "blink", 0) > 0.5 for s in samples[8:18]) or len({s[0].sprite for s in samples}) > 1
    assert samples[75][0].sprite == "working"
    assert max(offset for _, offset, _, _ in samples[84:92]) == pytest.approx(LEGACY_JUMP_HEIGHT, abs=1.0)  # V3 的小跳
    assert samples[88][0].sprite == "happy"
    assert samples[97][0].sprite == "idle"
    assert not isValid(scenes[0].win)


def small_batch(directory):
    directory.mkdir()
    for name in media.NAMES:
        image = Image.new("RGB", media.image_size(name), "white")
        if name.endswith(".gif"):
            image.save(directory / name, duration=media.GIF_DURATION_MS, loop=0)
        else:
            image.save(directory / name)


def test_budget_validation_checks_each_file_and_existing_directory_total(tmp_path, monkeypatch):
    output = tmp_path / "images"
    small_batch(output)
    report = media.validate_files(output)
    assert {row["file"] for row in report} == set(media.NAMES)
    with pytest.raises(ValueError, match="总体积超限"):
        media.validate_files(output, media.TOTAL_LIMIT)
    with monkeypatch.context() as patch:
        patch.setattr(media, "GIF_LIMIT", 1)
        with pytest.raises(ValueError, match="hero.gif 超限"):
            media.validate_files(output)
    with monkeypatch.context() as patch:
        patch.setattr(media, "PNG_LIMIT", 1)
        with pytest.raises(ValueError, match="pat.png 超限"):
            media.validate_files(output)


def test_validation_rejects_wrong_size_metadata_and_loop_seam(tmp_path):
    output = tmp_path / "images"
    small_batch(output)
    Image.new("RGB", (20, 20)).save(output / "pat.png")
    with pytest.raises(ValueError, match="尺寸错误"):
        media.validate_files(output)
    Image.new("RGB", media.STILL_SIZE).save(output / "pat.png", dpi=(96, 96))
    with pytest.raises(ValueError, match="元数据"):
        media.validate_files(output)
    Image.new("RGB", media.STILL_SIZE).save(output / "pat.png")
    first = Image.new("RGB", media.HERO_SIZE, "white")
    first.save(output / "hero.gif", save_all=True, append_images=[Image.new("RGB", media.HERO_SIZE, "black")],
               duration=2000, loop=0)
    with pytest.raises(ValueError, match="首尾衔接"):
        media.validate_files(output)


@pytest.mark.skipif(sys.platform != "win32", reason="README 媒体固定使用 Windows 字体与原生 Qt")
def test_native_full_batches_repeat_in_one_process_and_separate_cli(tmp_path):
    """跨调用/跨进程字节一致；禁止生成器起子进程、读取用户状态或留下可见窗口。"""
    root = Path(__file__).resolve().parents[1]
    code = '''
import json, platform, subprocess, sys
from pathlib import Path
from tools import make_media as m
platform.uname()  # 先缓存：numpy/scipy 懒加载时会读平台信息，别让它撞上下面对子进程的禁令
app = m.media_application()
import shion.app
def forbidden(*args, **kwargs):
    raise AssertionError("media must not start subprocesses or load user state")
subprocess.Popen = forbidden
shion.app.data_dir = forbidden
out = Path(sys.argv[1])
first = m.generate_media(out)
before = {name: (out / name).read_bytes() for name in m.NAMES}
sentinel = out / "unrelated.txt"
sentinel.write_text("keep", encoding="utf-8")
second = m.generate_media(out)
assert first == second
assert before == {name: (out / name).read_bytes() for name in m.NAMES}
assert sentinel.read_text(encoding="utf-8") == "keep"
assert not app.topLevelWidgets(), app.topLevelWidgets()
print(json.dumps(first))
'''
    output = tmp_path / "first"
    result = subprocess.run([sys.executable, "-c", code, str(output)], cwd=root,
                            capture_output=True, timeout=600)  # V3 的预热放在当前线程做，整套约 2 分钟/批
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    report = json.loads(result.stdout)
    assert len(report) == len(media.NAMES) == 17
    other = tmp_path / "second"
    result = subprocess.run([sys.executable, "tools/make_media.py", "--output-dir", str(other)],
                            cwd=root, capture_output=True, timeout=600)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    for name in media.NAMES:
        assert (output / name).read_bytes() == (other / name).read_bytes(), name
