"""S7 省内存：窗口用的 rig 把稀疏整画布遮罩换成 SparseCanvas 后，画面逐像素不变。"""
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from shion.v3_memory import SparseCanvas, compact_rig, placed
from tests.test_v3_display import qapp  # noqa: F401  (fixture)


def test_sparse_canvas_crop_matches_pil_crop_everywhere():
    for mode in ("L", "RGBA"):
        a = np.zeros((60, 80) if mode == "L" else (60, 80, 4), np.uint8)
        a[20:30, 40:55] = 200
        a[25, 10] = 7
        full = Image.fromarray(a)
        sparse = SparseCanvas(full)
        assert sparse.size == full.size and sparse.image.size == (45, 10)
        for box in ((0, 0, 80, 60), (35, 15, 60, 40), (-10, -5, 20, 30), (70, 50, 100, 90),
                    (41, 21, 42, 22), (0, 0, 5, 5)):
            assert np.array_equal(np.asarray(sparse.crop(box)), np.asarray(full.crop(box))), box
    empty = SparseCanvas(Image.new("L", (10, 10)))
    assert np.asarray(empty.crop((2, 2, 8, 8))).sum() == 0
    image, offset = placed(SparseCanvas(Image.fromarray(a)))
    assert offset == (10, 20)


@pytest.mark.parametrize("side", ["left", "right"])
def test_compact_rig_renders_identically(side):
    from v3proto.animation import Pose, Settings
    from v3proto.render import Renderer, Rig, premultiplied
    plain = Rig(cheek_side=side)
    small = compact_rig(Rig(cheek_side=side))
    assert isinstance(small.cheek_images["neutral"]["protect"], SparseCanvas)
    assert small.face_contour is None
    for expression in ("smug", "neutral"):
        assert np.array_equal(np.asarray(plain.rest(expression)), np.asarray(small.rest(expression)))
    a, b = Renderer(plain, .4), Renderer(small, .4)
    poses = (Pose(), Pose(eye_scale=.3), Pose(pinch_delta=(-60.0, 10.0)),
             Pose(reaction_face="dizzy", reaction_base="neutral"),
             Pose(reaction_face="teary", reaction_base="smug", eye_scale=.5))
    for expression in ("neutral", "smug", "happy", "sleep"):
        s = Settings(expression=expression)
        for pose in poses:
            if pose.reaction_face is not None:
                pose = replace(pose, reaction_base=expression)
            assert np.array_equal(premultiplied(a.render(s, pose)), premultiplied(b.render(s, pose))), \
                (expression, pose)


def test_window_rig_is_compacted():
    from shion.v3_window import load_rig
    rig = load_rig("left")
    assert all(isinstance(e["protect"], SparseCanvas) for e in rig.cheek_images.values())
    assert isinstance(rig.fringe_mask, SparseCanvas)


# ---- S9：姿势变体（scene）的内存 ----
SCENE_BUDGET_MB = 4.1   # 260 高、DPR1.5 下三个 scene 的 SceneImages 合计实测 3.54MB（2026-11-16，tools/v3_mem 同口径）× 1.15


@pytest.fixture
def scene_window(monkeypatch):
    """不开后台预热，用到哪个同步载入哪个；用完真正销毁窗口。"""
    from PySide6.QtCore import QCoreApplication, QEvent
    from shion.v3_window import V3PetWindow
    from tests.test_v3_display import make
    monkeypatch.setattr(V3PetWindow, "_v3_scene_prewarm", lambda self: None)
    made = []

    def build(app, height=260, dpr=1.5):
        w, _ = make(app, height, dpr)
        made.append(w)
        return w
    yield build
    for w in made:
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_load_arrays_keeps_no_full_layer():
    from shion import v3_scene
    scenes = v3_scene.load_metadata()
    assert scenes
    for scene in dict.fromkeys(scenes.values()):
        arrays = v3_scene.load_arrays(scene, 0.25)
        assert "full" not in arrays
        assert {"char", "furniture", "under", "seam", "alpha"} <= set(arrays)


def test_scene_images_stay_within_the_memory_budget(qapp, scene_window):  # noqa: F811
    w = scene_window(qapp)
    total = 0
    for scene in dict.fromkeys(w._v3_scenes.values()):
        images = w._v3_scene_images(scene)
        assert images is not None
        total += images.nbytes()
    assert total / 2 ** 20 <= SCENE_BUDGET_MB


def test_scene_cache_never_exceeds_its_limit(qapp, scene_window):  # noqa: F811
    from shion.v3_window import SCENE_CACHE
    w = scene_window(qapp, 200, 1.0)
    for dpr in (1.0, 1.25, 1.5, 2.0, 2.5, 1.0, 1.5):
        w.set_device_pixel_ratio(dpr)
        for scene in dict.fromkeys(w._v3_scenes.values()):
            w._v3_scene_images(scene)
        assert len(w._v3_scene_cache) <= SCENE_CACHE


def test_scenes_off_builds_no_cache_and_submits_no_jobs(qapp, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QCoreApplication, QEvent
    from tests.test_v3_display import make
    monkeypatch.setenv("SHION_V3_SCENES", "0")
    w, _ = make(qapp, 200, 1.0)
    try:
        assert w._v3_scenes is None
        assert not w._v3_scene_cache and not w._v3_scene_jobs
    finally:
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
