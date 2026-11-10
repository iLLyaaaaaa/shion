"""S7 省内存：窗口用的 rig 把稀疏整画布遮罩换成 SparseCanvas 后，画面逐像素不变。"""
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from shion.v3_memory import SparseCanvas, compact_rig, placed


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
