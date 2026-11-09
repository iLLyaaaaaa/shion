"""Right-side bulging cheek: only the skin is mirrored, the left rig is untouched."""
import numpy as np
import pytest
from PIL import ImageOps

from tests.test_v3_lift import rig
from v3proto.animation import Pose, Settings
from v3proto.mirror import EYE_MIDLINE_SUM, mirrored_box
from v3proto.render import Renderer, Rig, to_pil

M = EYE_MIDLINE_SUM


@pytest.fixture(scope='module')
def right():
    return Rig(cheek_side='right')


def test_left_rig_is_unchanged(rig):
    assert rig.mirror_sum is None
    order = rig.order
    assert order.index('side_hair_l') < order.index('head_skin') < order.index('side_hair_r')


def test_right_rig_flips_only_skin_and_swaps_side_hair(rig, right):
    assert right.mirror_sum == M
    order = right.order
    assert order.index('side_hair_r') < order.index('head_skin') < order.index('side_hair_l')
    skin, mirrored = rig.images['head_skin'], right.images['head_skin']
    assert mirrored.size == skin.size
    assert np.array_equal(np.asarray(mirrored), np.asarray(ImageOps.mirror(skin)))
    p, q = rig.parts['head_skin'], right.parts['head_skin']
    assert q['x'] == M - (p['x'] + skin.width - 1) and q['y'] == p['y']
    # Eyes, mouth and every hair layer keep their position.
    for name in ('side_hair_l', 'side_hair_r', 'bangs', 'ribbon', 'flower', 'expr_neutral_eye_l', 'expr_neutral_eye_r'):
        assert (right.parts[name]['x'], right.parts[name]['y']) == (rig.parts[name]['x'], rig.parts[name]['y'])
        assert np.array_equal(np.asarray(right.images['expr_neutral_eye_l']), np.asarray(rig.images['expr_neutral_eye_l']))


def test_old_cheek_is_gone_from_hair_slices(rig, right):
    x0, y0, x1, y1 = rig.cheek_config['box']
    for name in ('bangs', 'side_hair_l'):
        p = right.parts[name]
        before = np.asarray(rig.face_hair_images.get(name, rig.images[name]))
        after = np.asarray(right.face_hair_images.get(name, right.images[name]))
        assert (after[..., 3] > 0).sum() <= (before[..., 3] > 0).sum()
    # Hair outside the cheek zone is untouched.
    a = np.asarray(right.images['side_hair_r'])
    b = np.asarray(rig.images['side_hair_r'])
    assert np.array_equal(a, b)


def test_cheek_assets_mirror_about_the_sum(rig, right):
    box = rig.cheek_config['box']
    mx0, my0, mx1, my1 = mirrored_box(rig.cheek_config, M)
    assert (mx1 - mx0, my1 - my0) == (box[2] - box[0], box[3] - box[1])
    assert mx0 == M - (box[2] - 1) and mx1 == M - box[0] + 1
    for face in rig.faces:
        left = rig.cheek_images[face]
        mirrored = right.cheek_images[face]
        assert np.array_equal(np.asarray(mirrored['mask']), np.asarray(ImageOps.mirror(left['mask'])))
        # Canvas-sized protect mask: pixel i maps to M - i.
        ys, xs = np.nonzero(np.asarray(left['protect']))
        sel = (M - xs >= 0) & (M - xs < left['protect'].width)
        assert (np.asarray(mirrored['protect'])[ys[sel], M - xs[sel]] > 0).all()


def test_cheek_motion_is_a_reflection_of_the_left_motion(rig, right):
    from v3proto.cheek import Cheek
    from v3proto.animation import Settings
    left_cheek, right_cheek = Cheek(rig, .3), Cheek(right, .3)
    s = Settings(pinch_maximum=200)
    for delta in ((-110., -8.), (-60., 20.), (8., 0.)):
        pose = Pose(pinch_delta=delta)
        for x, y in ((330., 600.), (400., 560.), (470., 640.)):
            lx, ly = left_cheek.source_point((x, y), s, pose)
            rx, ry = right_cheek.source_point((M - x, y), s, pose)
            assert rx == pytest.approx(M - lx, abs=1e-6) and ry == pytest.approx(ly, abs=1e-6)


@pytest.mark.parametrize('side', ('left', 'right'))
def test_pinch_changes_pixels_only_on_the_bulging_side(side, rig, right):
    r = Renderer(rig if side == 'left' else right, .3)
    s = Settings()  # animated head path for both frames
    rest = np.asarray(to_pil(r.render(s, Pose(head_y=-1))))
    pulled = np.asarray(to_pil(r.render(s, Pose(head_y=-1, pinch_delta=(-110., -8.)))))
    diff = (rest != pulled).any(-1)
    xs = np.nonzero(diff.any(0))[0]
    assert len(xs)
    centre = (xs.min() + xs.max()) / 2 / .3
    assert (centre < M / 2) if side == 'left' else (centre > M / 2)
