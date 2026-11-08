"""Asset contracts, real renderer and offscreen interaction regression."""
import hashlib
import json
import os
from itertools import product
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from v3proto.animation import Pose, Settings, SWAY_PARTS
from v3proto.render import DEFAULT_RIG, Renderer, Rig, sample, to_pil
from v3proto.__main__ import save_snapshot


@pytest.fixture(scope="module")
def rig():
    return Rig()


def on_white(im):
    base = Image.new("RGBA", im.size, "white")
    base.alpha_composite(im)
    return base.convert("RGB")


def test_rest_matches_step0_pixel_digest_and_snapshot(rig, tmp_path):
    renderer = Renderer(rig, 1)
    out = tmp_path / "rest.png"
    save_snapshot(renderer, Settings(), Pose(), out)
    with Image.open(out) as im:
        assert im.size == (1086, 1448)
        original=on_white(rig.rest('smug',original=True))
        assert hashlib.sha256(original.tobytes()).hexdigest() == \
            "228447b58e515e96e504539d5ad64271c09037b26cfd73e7bca644f284becd29"
        expected=original.convert('RGBA')
        if rig.pink_cleanup is not None:expected.alpha_composite(rig.pink_cleanup)
        assert im.convert('RGB').tobytes()==expected.convert('RGB').tobytes()


@pytest.mark.parametrize("face", ["neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"])
def test_expression_split_reassembles_original_pixel_for_pixel(rig, face):
    combined = Image.new("RGBA", rig.size)
    for n in rig.face_parts(face):
        p = rig.parts[n]
        combined.alpha_composite(rig.images[n], (p["x"], p["y"]))
    # Original unsplit expression remains a reproducible asset input.
    original_path = DEFAULT_RIG.parent / "expressions" / f"expr_{face}.png"
    p = rig.data["expression_sources"][face]
    expected = Image.new("RGBA", rig.size)
    with Image.open(original_path) as im:
        expected.alpha_composite(im, (p["x"], p["y"]))
    assert combined.tobytes() == expected.tobytes()


def test_hierarchy_and_legs_stay_planted(rig):
    r = Renderer(rig)
    p = Pose(body_scale=1.012, head_y=-4, angles={"flower": 3, "bangs": 2})
    m = r.matrices(p)
    assert np.array_equal(m["leg_l"], np.eye(3))
    assert np.array_equal(m["hair_top"], m["head_skin"])
    assert np.array_equal(m["ribbon"], m["flower"])
    # Fringe rotation is now a continuous warp with its cut fixed to hair_top.
    assert np.array_equal(m["bangs"], m["hair_top"])


def test_expressions_do_not_paint_over_cheeks_and_face_base_keeps_blush(rig):
    skin=np.asarray(rig.images['head_skin'])
    base=np.asarray(rig.face_base)
    p=rig.parts['head_skin'];yy,xx=np.indices(skin.shape[:2]);xx+=p['x'];yy+=p['y']
    pink=((skin[...,0].astype(int)-skin[...,1]>32)&(skin[...,2].astype(int)-skin[...,1]>3)
          &(skin[...,0]>220)&(skin[...,1]>125)&(skin[...,3]>128)&(yy>560))
    assert np.array_equal(skin[pink],base[pink])
    for face in rig.faces:
        if face=='smug':continue
        alpha=Image.new('RGBA',rig.size)
        for n in rig.face_parts(face):
            part=rig.parts[n];alpha.alpha_composite(rig.images[n],(part['x'],part['y']))
        a=np.asarray(alpha)[...,3]
        assert not a[582:625,350:425].any(), face
        assert not a[575:605,635:695].any(), face


def test_runtime_leg_gap_has_no_bright_thread(rig):
    r=Renderer(rig,1)
    a=np.asarray(to_pil(r.render(Settings(),Pose(head_y=-3,body_scale=1.01))))
    assert a[1200,550,3]<8


def test_complete_plate_keeps_cheek_and_contour_during_blink(rig):
    from v3proto.face import plate_face
    plate,origin=rig.face_plate
    # Above the old blush crop: these must stay pink, not become white boxes.
    for point in ((366,553),(674,531)):
        x,y=point[0]-origin[0],point[1]-origin[1]
        c=np.array(plate.getpixel((x,y)),dtype=int)
        assert c[3]==255 and c[0]-c[1]>40 and c[2]>c[1]
    # These fringe tips must remain identical through every expression/blink.
    for face in rig.faces:
        for scale in (1,.55,.1):
            image,_=plate_face(rig,face,scale)
            for x,y in ((488,477),(535,472)):
                q=(x-origin[0],y-origin[1])
                expected=rig.expression_plates[face][0] if face in rig.expression_plates else plate
                assert image.getpixel(q)==expected.getpixel(q)


def test_closed_eyes_reveal_skin_and_fringe_tips_do_not_blink(rig):
    r=Renderer(rig,1)
    # These two tips were previously hidden in eye_ref and collapsed on blink.
    tips=[(485,473,491,477),(520,469,536,474)]
    for face in rig.faces:
        s=Settings(expression=face)
        opened=np.asarray(to_pil(r.render(s,Pose(head_y=-1))))
        closed=np.asarray(to_pil(r.render(s,Pose(head_y=-1,eye_scale=.1))))
        for x0,y0,x1,y1 in tips:
            assert np.array_equal(opened[y0:y1,x0:x1],closed[y0:y1,x0:x1]),face
        # Former gray/white eye shadows must be warm skin, not an inpaint cloud.
        for x,y in ((400,510),(630,490)):
            c=closed[y,x,:3].astype(int)
            assert c.min()>210 and 15<=c[0]-c[1]<=40,(face,(x,y),c)


def test_shared_head_surface_does_not_fold_at_extreme_sway(rig):
    surface=Renderer(rig).head_surface
    for values in product(*[(-12,12) if n=='ahoge' else (-3,3) for n in SWAY_PARTS]):
        x,y=surface.coordinates(Pose(angles=dict(zip(SWAY_PARTS,values))))
        xy,xx=np.gradient(x,surface.step_y,surface.step_x)
        yy,yx=np.gradient(y,surface.step_y,surface.step_x)
        # A negative determinant would fold a shared contour back over itself.
        assert (xx*yy-xy*yx).min()>.1
        # Also check the actual coarser drawing mesh, at all four corners of
        # every cell, rather than only its dense source coordinate field.
        _,mx,my=surface.mesh(Pose(angles=dict(zip(SWAY_PARTS,values))))
        for u,v in product((0,1),repeat=2):
            dx=((1-v)*(mx[:-1,1:]-mx[:-1,:-1])+v*(mx[1:,1:]-mx[1:,:-1]))/np.diff(surface.mesh_x)
            dy=((1-v)*(my[:-1,1:]-my[:-1,:-1])+v*(my[1:,1:]-my[1:,:-1]))/np.diff(surface.mesh_x)
            ex=((1-u)*(mx[1:,:-1]-mx[:-1,:-1])+u*(mx[1:,1:]-mx[:-1,1:]))/np.diff(surface.mesh_y)[:,None]
            ey=((1-u)*(my[1:,:-1]-my[:-1,:-1])+u*(my[1:,1:]-my[:-1,1:]))/np.diff(surface.mesh_y)[:,None]
            assert (dx*ey-dy*ex).min()>.1


def test_reference_eyes_have_no_detached_ink_at_half_blink(rig):
    from scipy import ndimage as nd
    from v3proto.face import complete_eye
    for name in ('eye_ref_l','eye_ref_r'):
        eye=complete_eye(rig,name)
        eye=eye.resize((eye.width,round(eye.height*.55)),Image.Resampling.LANCZOS)
        labels,count=nd.label(np.asarray(eye)[...,3]>128,np.ones((3,3)))
        areas=np.bincount(labels.ravel(),minlength=count+1)[1:]
        assert (areas>5).sum()==1


def test_happy_pink_marks_removed_from_all_face_layers(rig):
    from v3proto.face import plate_face
    box=(405,480,462,497)
    for role in ('eye_l','mouth'):
        name=next(n for n in rig.face_parts('happy') if rig.parts[n]['role']==role)
        p=rig.parts[name];canvas=Image.new('RGBA',rig.size)
        canvas.alpha_composite(rig.images[name],(p['x'],p['y']))
        c=np.asarray(canvas.crop(box)).astype(int)
        pink=(c[...,3]>128)&(c[...,0]>215)&(c[...,1]<210)&(c[...,2]>c[...,1])
        assert pink.sum()==0
    baseline,origin=plate_face(rig,'happy',1)
    local=tuple(v-origin[i%2] for i,v in enumerate(box))
    for scale in (.55,.1):
        frame,_=plate_face(rig,'happy',scale)
        for x,y in ((432,487),(591,467)):
            c=np.array(frame.getpixel((x-origin[0],y-origin[1])),dtype=int)
            assert c[1]>210 and c[0]-c[1]<35


def test_smug_upper_bang_arcs_survive_breath_and_blink(rig):
    from v3proto.animation import Animator
    boxes=((338,365,421,422),(548,337,650,370))
    r=Renderer(rig,1)
    rest=rig.rest('smug')
    baseline=[(np.asarray(rest.crop(b))[...,:3].max(-1)<170).sum() for b in boxes]
    animator=Animator(Settings())
    for _ in range(16):
        pose=animator.advance(.4)
        frame=to_pil(r.render(Settings(),pose))
        for box,area in zip(boxes,baseline):
            shifted=(box[0],round(box[1]+pose.head_y),box[2],round(box[3]+pose.head_y))
            assert (np.asarray(frame.crop(shifted))[...,:3].max(-1)<170).sum()>=area*.65


def test_pink_cleanup_changes_only_local_skin():
    from tools.v3_pink_marks import remove_marks
    from PIL import ImageDraw
    im=Image.new('RGBA',(1086,1448),(254,229,225,255))
    draw=ImageDraw.Draw(im)
    draw.line([(395,450),(425,448)],fill=(235,135,148,255),width=7)
    draw.line([(390,440),(430,440)],fill=(85,30,35,255),width=3)
    clean,mask=remove_marks(im,'smug')
    a,b=np.asarray(im),np.asarray(clean)
    assert mask.sum()>100
    assert np.array_equal(a[~mask],b[~mask])
    dark=a[...,:3].max(-1)<170
    assert np.array_equal(a[dark],b[dark])
    again,_=remove_marks(clean,'smug')
    assert np.array_equal(np.asarray(again),b)


def test_head_mesh_identity_retains_full_resolution_pixels(rig):
    from v3proto.render import premultiplied
    surface=Renderer(rig).head_surface
    settings=Settings(expression='neutral')
    expected=surface.compose(settings,Pose())
    # Enters the mesh path, but rounds to a zero-degree field. Even fine ink
    # must remain pixel-identical rather than being downsampled and enlarged.
    actual=premultiplied(surface.render(settings,Pose(angles={'bangs':.01})))
    assert np.array_equal(expected,actual)


def test_small_breath_moves_head_at_subpixel_precision(rig):
    r=Renderer(rig,.4)
    a=np.asarray(to_pil(r.render(Settings(),Pose(head_y=-1))))[:260]
    b=np.asarray(to_pil(r.render(Settings(),Pose(head_y=-1.1))))[:260]
    assert not np.array_equal(a,b)
    assert np.abs(a.astype(int)-b.astype(int)).mean()<1


@pytest.mark.parametrize("face", ["smug", "neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"])
def test_blink_and_extreme_pinch_render_finite_and_mouth_static(rig, face):
    r, s = Renderer(rig), Settings(expression=face, pinch_maximum=200, pinch_radius=60)
    open_face = to_pil(r._face(s, Pose()))
    closed_face = to_pil(r._face(s, Pose(eye_scale=0.1)))
    # Mouth center below both eye windows must not change during blinking.
    t = r.face_texture
    box = tuple(round(v * r.scale) for v in (505-t.x, 560-t.y, 555-t.x, 590-t.y))
    assert open_face.crop(box).tobytes() == closed_face.crop(box).tobytes()
    im = to_pil(r.render(s, Pose(eye_scale=0.1, pinch_delta=(200, 0))))
    a = np.asarray(im)
    assert a.shape == (579, 434, 4) and (a[..., 3] > 0).any()


def test_premultiplied_sampling_has_no_white_fringe():
    a = np.zeros((20, 20, 4), np.uint8)
    a[5:15, 5:15] = [100, 20, 0, 255]
    y, x = np.indices((20, 20), dtype=np.float32)
    im = np.asarray(to_pil(sample(a, x + 0.5, y)))
    edge = (im[..., 3] > 0) & (im[..., 3] < 255)
    assert edge.any()
    assert im[..., 0][edge].max() <= 102


def test_underlay_mode_and_hit_testing(rig):
    r = Renderer(rig)
    s = Settings(underlays_only=True)
    assert r.render(s, Pose()).size().width() == 434
    s.underlays_only = False
    assert r.hit_test((530, 580), s, Pose())[0] == "face"
    assert r.hit_test((500, 150), s, Pose())[0] == "head"
    assert r.hit_test((0, 0), s, Pose())[0] is None
    assert r.hit_test((530, 576), s, Pose(head_y=-4))[0] == "face"


def test_window_controls_and_mouse_coordinates(rig):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QSlider
    from PySide6.QtCore import QPointF
    from v3proto.window import Preview
    app = QApplication.instance() or QApplication([])
    w = Preview(rig, Settings())
    try:
        sliders = {k: obj for obj, k, _ in w.controls if isinstance(obj, QSlider)}
        assert (sliders["pinch_maximum"].minimum(), sliders["pinch_maximum"].maximum(),
                sliders["pinch_maximum"].value()) == (20, 200, 120)
        assert (sliders["pinch_radius"].minimum(), sliders["pinch_radius"].maximum(),
                sliders["pinch_radius"].value()) == (60, 160, 110)
        sliders["pinch_maximum"].setValue(200)
        assert w.settings.pinch_maximum == 200
        class Event:
            def position(self):
                return QPointF(12 + 530 * 0.4, 12 + 580 * 0.4)
        assert w.canvas.point(Event()) == pytest.approx([530, 580])
        w.reset()
        assert w.settings.pinch_maximum == 120
    finally:
        w.close()
        app.processEvents()


@pytest.mark.parametrize('expression,box', [
    ('neutral',(550,420,700,485)),
    ('smug',(300,430,745,520)),
    ('teary',(305,465,480,525)),
    ('angry',(555,445,700,495)),
])
def test_source_eyelid_and_fringe_survive_animated_head(rig,expression,box):
    opened,origin=rig.expression_plates[expression]
    expected=np.asarray(opened.crop(tuple(v-origin[i%2] for i,v in enumerate(box))))
    ink=(expected[...,:3].max(-1)<170)&(expected[...,3]>250)
    assert ink.sum()>150
    renderer=Renderer(rig,1)
    for offset in (-1,-3,-5):
        frame=to_pil(renderer.render(Settings(expression=expression),Pose(head_y=offset)))
        actual=np.asarray(frame.crop((box[0],box[1]+offset,box[2],box[3]+offset)))
        # Original stroke colors and thickness must survive entry into the
        # animated path, including the shared fringe/eyelid boundary.
        difference=np.abs(actual[...,:3].astype(int)-expected[...,:3]).max(-1)[ink]
        # Feathered outer plate edges can be covered by the original flower;
        # at least 98% of the interior ink must retain its exact source color.
        assert (difference<=1).mean()>.98


@pytest.mark.parametrize('expression',['smug','neutral','teary','angry'])
def test_blink_has_continuous_entry_exit_and_stationary_face(rig,expression):
    from v3proto.face import plate_face
    opened=np.asarray(plate_face(rig,expression,1)[0]).astype(int)
    # A nearly open eye must not switch thousands of unrelated face pixels.
    adjacent=np.asarray(plate_face(rig,expression,1-1e-6)[0]).astype(int)
    assert np.abs(adjacent-opened).max()<=1
    _,origin=rig.face_plate
    yy,xx=np.indices(opened.shape[:2]);xx+=origin[0];yy+=origin[1]
    # Covers forehead/fringe above eyes, mouth and cheek interior below eyes.
    fixed=(yy<420)|((yy>585)&(xx>490)&(xx<590))
    for scale in (.999,.98,.9,.55,.1):
        image=np.asarray(plate_face(rig,expression,scale)[0]).astype(int)
        assert np.array_equal(image[fixed],opened[fixed])
