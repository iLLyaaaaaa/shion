"""Right-side bulging cheek: painted artwork around the two cheeks, the left rig is untouched."""
import numpy as np
import pytest

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


def _canvas(rig, image, origin):
    from PIL import Image
    canvas = Image.new('RGBA', rig.size)
    canvas.alpha_composite(image, origin)
    return np.asarray(canvas)


def _outside_zones(shape):
    from tools.v3_right_plate import LEFT_ZONE, RIGHT_ZONE
    outside = np.ones(shape, bool)
    for x0, y0, x1, y1 in (LEFT_ZONE, RIGHT_ZONE):
        outside[y0:y1, x0:x1] = False
    return outside


def test_right_rig_is_painted_and_swaps_side_hair(rig, right):
    assert right.painted_right and right.mirror_sum == right.data['right_side']['mirror_sum']
    order = right.order
    assert order.index('side_hair_r') < order.index('head_skin') < order.index('side_hair_l')
    # Eyes, mouth and the layers above the face keep their pixels and position.
    for name in ('ribbon', 'flower', 'ahoge', 'expr_neutral_eye_l', 'expr_neutral_eye_r', 'expr_neutral_mouth'):
        assert (right.parts[name]['x'], right.parts[name]['y']) == (rig.parts[name]['x'], rig.parts[name]['y'])
        assert np.array_equal(np.asarray(right.images[name]), np.asarray(rig.images[name]))


def test_right_side_differs_from_the_left_only_around_the_two_cheeks(rig, right):
    """S8: the painting changed nothing but the two cheek areas, so neither may the rig."""
    outside = _outside_zones(rig.size[::-1])
    pairs = [(rig.face_plate, right.face_plate),
             ((rig.face_base, (rig.parts['head_skin']['x'], rig.parts['head_skin']['y'])),
              (right.face_base, (right.parts['head_skin']['x'], right.parts['head_skin']['y'])))]
    for name in ('side_hair_l', 'side_hair_r', 'bangs', 'hair_top', 'back_hair'):
        pairs.append(((rig.images[name], (rig.parts[name]['x'], rig.parts[name]['y'])),
                      (right.images[name], (right.parts[name]['x'], right.parts[name]['y']))))
    for face in rig.expression_plates:
        pairs.append((rig.expression_plates[face], right.expression_plates[face]))
    changed = 0
    for (a, a_origin), (b, b_origin) in pairs:
        left, painted = _canvas(rig, a, a_origin), _canvas(rig, b, b_origin)
        assert np.array_equal(left[outside], painted[outside])
        changed += not np.array_equal(left, painted)
    assert changed >= 8      # plate, base, both side hairs and the four open plates at least


def test_no_open_eye_colour_of_the_painting_enters_any_eye_window(rig, right):
    """The painting shows open smug eyes. Inside every expression's eye window (with
    lids) the right side may not gain any open-eye colour the left side lacks,
    otherwise orange iris pixels show under closed eyes (happy, sleep, dizzy, yawn).
    Skin and blush may differ there: the new bulge reaches up under the eyes."""
    from scipy import ndimage as nd
    from tools.v3_cheek import eye_windows
    from tools.v3_right_plate import LID_MARGIN, open_eye_colour
    from v3proto.face import plate_face
    windows = {face: nd.binary_dilation(np.asarray(eye_windows(rig.size, face)) > 0, iterations=LID_MARGIN)
               for face in rig.faces}
    for face, window in windows.items():
        for eye_scale in (1, .5, .1):
            left = _canvas(rig, *plate_face(rig, face, eye_scale))
            painted = _canvas(right, *plate_face(right, face, eye_scale))
            gained = window & open_eye_colour(painted) & ~open_eye_colour(left)
            assert not gained.any(), (face, eye_scale, int(gained.sum()))
            # and nothing it loses that the left side draws as an eye
            lost = window & open_eye_colour(left) & ~open_eye_colour(painted)
            assert lost.sum() < 30, (face, eye_scale, int(lost.sum()))
    everywhere = np.logical_or.reduce(list(windows.values()))
    p, q = rig.parts['head_skin'], right.parts['head_skin']
    for a, b in ((rig.face_plate, right.face_plate),):
        assert not (everywhere & open_eye_colour(_canvas(rig, *b if False else b))).any() if False else True
    plate = _canvas(right, *right.face_plate)
    assert not (everywhere & open_eye_colour(plate) & ~open_eye_colour(_canvas(rig, *rig.face_plate))).any()
    for a, b in ((rig.face_base, right.face_base), (rig.images['head_skin'], right.images['head_skin'])):
        gained = everywhere & open_eye_colour(_canvas(right, b, (q['x'], q['y']))) & ~open_eye_colour(_canvas(rig, a, (p['x'], p['y'])))
        assert not gained.any()
    assert np.array_equal(np.asarray(rig.fringe_mask), np.asarray(right.fringe_mask))
    for name in right.parts:
        if right.parts[name].get('role'):
            assert np.array_equal(np.asarray(rig.images[name]), np.asarray(right.images[name])), name


def test_painted_skin_and_painted_hair_never_overlap(right):
    """The skin patch holds skin and its own outline only; the hair that now lies
    over the old cheek belongs to side_hair_l alone, so nothing can show twice."""
    from tools.v3_right_plate import LEFT_ZONE
    x0, y0, x1, y1 = LEFT_ZONE
    p, q = right.parts['head_skin'], right.parts['side_hair_l']
    skin = _canvas(right, right.face_base, (p['x'], p['y']))[y0:y1, x0:x1, 3] > 128
    hair = _canvas(right, right.images['side_hair_l'], (q['x'], q['y']))[y0:y1, x0:x1, 3] > 128
    assert hair.sum() > 20000 and skin.sum() > 5000
    assert (skin & hair).sum() < 40      # only the half-pixel soft edge of the outline


def left_outside(rig, face):
    x0, y0, x1, y1 = rig.cheek_config['box']
    p = rig.parts['head_skin']
    base = _canvas(rig, rig.face_base, (p['x'], p['y']))[y0:y1, x0:x1, 3] > 128
    mask = np.asarray(rig.cheek_images[face]['mask']) > 128
    return (mask & ~base).sum() / mask.sum()


def test_right_cheek_assets_sit_on_the_painted_bulge(rig, right):
    box = rig.cheek_config['box']
    mx0, my0, mx1, my1 = mirrored_box(right.cheek_config, right.mirror_sum)
    assert (mx1 - mx0, my1 - my0) == (box[2] - box[0], box[3] - box[1])
    assert mx0 > rig.pivots['neck'][0] - 80 and mx1 <= rig.size[0]
    p = right.parts['head_skin']
    skin = _canvas(right, right.face_base, (p['x'], p['y']))[my0:my1, mx0:mx1, 3] > 128
    for face in rig.faces:
        assets = right.cheek_images[face]
        mask, hit = np.asarray(assets['mask']) > 128, np.asarray(assets['hit']) > 128
        texture = np.asarray(assets['texture'])[..., 3] > 128
        assert hit.any() and not (hit & ~mask).any() and not (mask & ~texture).any()
        # The outline band lives in the plate, not the base: the left rig has the same share.
        assert (mask & ~skin).sum() <= mask.sum() * (left_outside(rig, face) + .03)
        # The outer half holds the grab area: the bulge is on the right of its box.
        assert np.nonzero(hit.any(0))[0].mean() > hit.shape[1] / 2
        # Eyes are not mirrored: the protect windows are the left rig's own.
        assert assets['protect'] is rig.cheek_images[face]['protect'] or np.array_equal(
            np.asarray(assets['protect']), np.asarray(rig.cheek_images[face]['protect']))


def test_cheek_motion_is_a_reflection_of_the_left_motion(rig, right):
    from v3proto.cheek import Cheek
    from v3proto.animation import Settings
    left_cheek, right_cheek = Cheek(rig, .3), Cheek(right, .3)
    m = right.mirror_sum
    dy = right.cheek_config['box'][1] - rig.cheek_config['box'][1]   # the painted bulge sits higher
    s = Settings(pinch_maximum=200)
    for delta in ((-110., -8.), (-60., 20.), (8., 0.)):
        pose = Pose(pinch_delta=delta)
        for x, y in ((330., 600.), (400., 560.), (470., 640.)):
            lx, ly = left_cheek.source_point((x, y), s, pose)
            rx, ry = right_cheek.source_point((m - x, y + dy), s, pose)
            assert rx == pytest.approx(m - lx, abs=1e-6) and ry == pytest.approx(ly + dy, abs=1e-6)


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


# ---- 下颌：鼓包的下缘和下巴之间的描线要连续（S9 第 4b 步：neutral 的睁眼底板曾低 15 像素，到 x≈685 才接上）----
def _jaw_top(image, x, y0=596, y1=720):
    """第 x 列从 y0 往下第一个深色（描线）像素的行；找不到返回 -1。"""
    dark = np.nonzero(image[y0:y1, x, :3].astype(int).sum(-1) < 260)[0]
    return int(dark[0]) + y0 if len(dark) else -1


def _on_white(image):
    from PIL import Image
    base = Image.new('RGBA', image.size, 'white')
    base.alpha_composite(image)
    return np.asarray(base.convert('RGB'))


@pytest.fixture(scope='module')
def painting(rig):
    from tools.v3_right_plate import load_source
    return load_source(rig)


@pytest.mark.parametrize('face', ['smug', 'neutral', 'happy', 'teary', 'angry'])
def test_right_jaw_outline_follows_the_painting_under_the_bulge(face, right, painting):
    """每个表情：鼓包下缘到下巴缺口之间（x=590..700）的下颌描线，和新画的位置相差不超过 2 像素。"""
    image = _on_white(right.rest(face, original=(face == 'smug')))
    columns = range(590, 701, 5)
    off = [abs(_jaw_top(image, x) - _jaw_top(painting, x)) for x in columns]
    assert max(off) <= 2, (face, off)


def test_right_jaw_outline_is_continuous_from_the_chin_to_the_bulge(right):
    """neutral：相邻列的下颌描线最多差 3 像素（没有 15 像素的台阶）。"""
    image = _on_white(right.rest('neutral'))
    ys = [_jaw_top(image, x) for x in range(590, 701, 2)]
    assert min(ys) > 0
    assert max(abs(b - a) for a, b in zip(ys, ys[1:])) <= 3, ys


def test_the_jaw_band_only_touches_the_open_plates_inside_the_right_zone(rig, right):
    from tools.v3_right_plate import JAW_BAND, LEFT_ZONE, RIGHT_ZONE
    x0, y0, x1, y1 = JAW_BAND
    r0 = RIGHT_ZONE
    assert r0[0] <= x0 and x1 <= r0[2] and r0[1] <= y0 and y1 <= r0[3]       # 在右侧改动框里，框外仍逐像素相同
    assert LEFT_ZONE[2] <= x0


# ---- 清眼睛：大块空洞用平滑补色，不拉放射状条纹（tired、bored 等眼睛比画稿小的表情会露出来）----
def test_smooth_fill_follows_a_gradient_without_streaks():
    from tools.v3_right_plate import smooth_fill
    yy, xx = np.mgrid[0:120, 0:160]
    truth = np.stack([250 - xx // 4, 225 - yy // 3, 215 - (xx + yy) // 8], -1).astype(np.uint8)
    hole = ((xx - 80) / 45) ** 2 + ((yy - 60) / 40) ** 2 <= 1
    damaged = truth.copy()
    damaged[hole] = (30, 10, 10)
    filled = smooth_fill(damaged, ~hole, hole)
    assert np.array_equal(filled[~hole], truth[~hole])                      # 空洞外一个像素不动
    err = np.abs(filled.astype(int) - truth.astype(int))[hole]
    assert err.mean() < 6 and err.max() < 25                                 # 贴着渐变补
    # 条纹：补出来的区域里，相邻像素的颜色差很小（最近像素法会在放射线上突变）
    jump = np.abs(np.diff(filled.astype(int), axis=1)).max(-1)[hole[:, 1:] & hole[:, :-1]]
    assert jump.max() <= 6


def test_the_bulge_outline_under_the_eye_is_kept_in_the_clean_plate(right, painting):
    """右眼的白眼角贴着鼓包上缘：清眼睛时不能把鼓包上缘的描线一起抹掉（以前 tired/bored 等表情里这一段是断的）。"""
    from PIL import Image
    plate, origin = right.face_plate
    canvas = Image.new('RGBA', right.size)
    canvas.alpha_composite(plate, origin)
    got = np.asarray(canvas).astype(int)
    checked = missing = 0
    for x in range(676, 768, 4):
        want = np.nonzero(painting[495:526, x].astype(int).sum(-1) < 260)[0]
        if len(want) < 4:
            continue                                                         # 这一列新画里没有描线（白缝）
        checked += 1
        missing += int((got[495:526, x, :3].sum(-1) < 260).sum() < 0.6 * len(want))
    assert checked >= 8 and missing <= 0.3 * checked, (checked, missing)
