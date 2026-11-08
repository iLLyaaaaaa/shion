"""Local cheek geometry and actual renderer/interaction regression."""
import os
from itertools import product
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from v3proto.animation import Animator,Pose,Settings
from v3proto.render import Rig,Renderer,to_pil
from v3proto.motion import (cheek_displacement,cheek_forward,cheek_inverse,limit_cheek_drag)

@pytest.fixture(scope='module')
def rig():return Rig()

@pytest.mark.parametrize('radius',[60,110,160])
def test_cheek_cage_invertible_extremes_and_rigid_cap(rig,radius):
    region=rig.cheek_config
    y,x=np.mgrid[530:681:2,60:471:2].astype(np.float32)
    for d in product((-200,12),(-24,24)):
        fx,fy=cheek_forward(x,y,d,radius,region)
        determinant=np.gradient(fx,2,axis=1)*np.gradient(fy,2,axis=0)-np.gradient(fx,2,axis=0)*np.gradient(fy,2,axis=1)
        assert determinant.min()>.1
        sx,sy=cheek_inverse(fx,fy,d,radius,region)
        assert np.hypot(sx-x,sy-y).max()<.003
        cap=(x<=region['cap_x'])&(y>=584)&(y<=628)
        assert np.allclose(fx[cap]-x[cap],d[0])
        assert np.allclose(fy[cap]-y[cap],d[1])
        fixed=(x>=region['root_x'])|(y<=536)|(y>=676)
        assert np.array_equal(fx[fixed],x[fixed])
        assert np.array_equal(fy[fixed],y[fixed])


def test_cheek_limits_and_regrab_have_no_jump():
    assert np.array_equal(limit_cheek_drag((1000,1000),200),(12,24))
    assert np.linalg.norm(limit_cheek_drag((-999,999),200))==pytest.approx(200)
    a=Animator(Settings());a.press((325,610));a.drag((205,610));a.release()
    a.advance(.04);before=a.delta.copy();a.press((210,610));a.drag((210,610))
    assert np.array_equal(a.delta,before)
    xs=[]
    a.release()
    for _ in range(360):
        p=a.advance(1/120);d=cheek_displacement(p.pinch_delta,120)
        assert -120<=d[0]<=12 and abs(d[1])<=24
        xs.append(d[0])
    assert max(xs)>1 and np.array_equal(a.delta,[0,0])
    a.press((325,610));a.drag((205,610));a.settings.expression='happy';a.advance(0)
    assert not a.dragging and np.array_equal(a.delta,[0,0])


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_cheek_keeps_eyes_mouth_hair_and_entry_continuous(rig,face):
    r=Renderer(rig,.6);s=Settings(expression=face,pinch_maximum=200)
    baseline=np.asarray(to_pil(r.render(s,Pose(head_y=-1)))).astype(int)
    adjacent=np.asarray(to_pil(r.render(s,Pose(head_y=-1,pinch_delta=(-1e-6,0))))).astype(int)
    assert np.abs(adjacent-baseline).max()<=1
    # All pixels outside the local surface's reachable region must be exact.
    yy,xx=np.indices(baseline.shape[:2]);xx=xx/.6;yy=yy/.6
    fixed=(xx>450)|(yy<530)|(yy>710)
    for d in ((-120,0),(-200,-24),(-200,24),(12,0)):
        a=np.asarray(to_pil(r.render(s,Pose(head_y=-1,pinch_delta=d)))).astype(int)
        assert np.array_equal(a[fixed],baseline[fixed])
        for box in ((345,470,480,535),(500,535,580,635),(550,430,700,530)):
            x0,y0,x1,y1=[round(v*.6) for v in box]
            assert np.array_equal(a[y0:y1,x0:x1],baseline[y0:y1,x0:x1])
    # The displaced rounded end must carry dark contour ink, not just skin.
    a=np.asarray(to_pil(r.render(s,Pose(head_y=-1,pinch_delta=(-120,0)))))
    ink=a[round(575*.6):round(630*.6),round(145*.6):round(180*.6),:3].max(-1)<190
    assert ink.sum()>15


def test_only_left_cheek_is_grabbable_and_outside_drag_continues(rig):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    r=Renderer(rig);s=Settings();p=Pose(head_y=-1)
    assert r.hit_test((325,609),s,p)[0]=='cheek'
    assert r.hit_test((530,580),s,p)[0]=='face'
    assert r.hit_test((650,580),s,p)[0]!='cheek'
    assert r.hit_test((410,510),s,p)[0]!='cheek'
    from v3proto.window import Preview
    from PySide6.QtCore import QPointF,Qt
    from PySide6.QtGui import QFocusEvent
    w=Preview(rig,s);c=w.canvas
    c.grabMouse=lambda:None
    class Event:
        def __init__(self,x,y):
            ox,oy=c.image_origin
            self.xy=QPointF(ox+x*.4,oy+y*.4)
        def position(self):return self.xy
        def button(self):return Qt.MouseButton.LeftButton
    try:
        c.mousePressEvent(Event(530,580));assert not c.animator.dragging
        c.mousePressEvent(Event(325,610));assert c.animator.dragging
        c.mouseMoveEvent(Event(-200,610));assert c.animator.delta[0]<-119
        assert c.animator.settings.expression=='smug'
        c.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut));assert not c.animator.dragging
    finally:w.close();app.processEvents()


def test_empty_mesh_cell_pruning_is_pixel_exact(rig):
    from PIL import Image
    r=Renderer(rig,.6);surface=r.head_surface
    settings=Settings(pinch_maximum=200,pinch_radius=60)
    for d in ((0,0),(-200,-24)):
        pose=Pose(eye_scale=.55,pinch_delta=d,angles={'ahoge':12,'flower':-3,'side_hair_l':3,'bangs':-3})
        a=surface.compose(settings,pose)
        image=Image.frombytes('RGBa',(surface.w,surface.h),a.tobytes())
        mesh,_,_=surface.mesh(pose)
        full=image.transform(image.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
        pruned=surface.visible_cells(mesh,a[...,3])
        assert len(pruned)<len(mesh)
        actual=image.transform(image.size,Image.Transform.MESH,pruned,Image.Resampling.BILINEAR)
        assert actual.tobytes()==full.tobytes()
        from v3proto.render import premultiplied
        assert np.array_equal(premultiplied(surface.render(settings,pose)),np.asarray(full))


def test_interleaved_sampler_matches_scipy_and_keeps_premultiplied_edges():
    from scipy import ndimage as nd
    from v3proto.cheek import bilinear_rgba
    rng=np.random.default_rng(17)
    a=rng.integers(0,256,(30,40,4),dtype=np.uint8)
    a[...,:3]=np.minimum(a[...,:3],a[...,3,None])
    x=rng.uniform(-2,42,(25,35)).astype(np.float32)
    y=rng.uniform(-2,32,(25,35)).astype(np.float32)
    expected=np.stack([nd.map_coordinates(a[...,c],[y,x],order=1,mode='constant',cval=0,prefilter=False) for c in range(4)],-1)
    actual=bilinear_rgba(a,x,y)
    assert np.abs(expected.astype(int)-actual.astype(int)).max()<=1
    assert (actual[...,:3]<=actual[...,3,None]).all()


@pytest.mark.parametrize('radius',[60,110,160])
def test_horizontal_lookup_matches_full_inverse(rig,radius):
    from v3proto.cheek import horizontal_inverse
    y,x=np.mgrid[530:681:3.7,70:471:3.9].astype(np.float32)
    for dx in (-200,-120,12):
        expected,_=cheek_inverse(x,y,(dx,0),radius,rig.cheek_config)
        actual=horizontal_inverse(x,y,dx,radius,rig.cheek_config)
        assert np.abs(actual-expected).max()<.06


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_pinch_alone_preserves_exact_rest_and_fixed_pixels(rig,face):
    r=Renderer(rig,.4)
    s=Settings(expression=face,breath=False,blink=False,sway=False)
    from v3proto.render import premultiplied
    a=premultiplied(r.render(s,Pose())).astype(int)
    near=premultiplied(r.render(s,Pose(pinch_delta=(-1e-6,0)))).astype(int)
    assert np.abs(a-near).max()<=1
    pulled=premultiplied(r.render(s,Pose(pinch_delta=(-120,0)))).astype(int)
    y,x=np.indices(a.shape[:2]);fixed=(x>450*.4)|(y<530*.4)|(y>710*.4)
    assert np.array_equal(a[fixed],pulled[fixed])


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_transport_material_has_continuous_skin_and_no_upper_hair_wedge(rig,face):
    texture=np.asarray(rig.cheek_images[face]['texture'])
    x0,y0,_,_=rig.cheek_config['box']
    # The moving sheet needs hidden skin beneath fixed eyes. Cutting the eye
    # alpha out of this material creates a travelling hole which reveals hair.
    body=texture[550-y0:575-y0,345-x0:435-x0]
    assert body[...,3].min()==255
    assert body[...,:3].max(-1).min()>210
    # A cheek's upper left silhouette descends smoothly towards its round end.
    # The old flood included a fringe lobe that turned back towards the right.
    left=[]
    for row in texture[:584-y0,:,3]:
        left.append(np.flatnonzero(row>128).min())
    assert np.diff(left).max()<=1


@pytest.mark.parametrize('face',['teary','neutral','happy'])
def test_old_eye_corner_does_not_reappear_inside_pulled_cheek(rig,face):
    r=Renderer(rig,1);s=Settings(expression=face,pinch_maximum=200)
    for amount in (80,120,200):
        for eyes in (1,.55,.1):
            image=np.asarray(to_pil(r.render(s,Pose(head_y=-1,eye_scale=eyes,pinch_delta=(-amount,0)))))
            # The user-reported dark triangle at the old cheek/eye junction is
            # now inside the stretched skin, clear of the new outer contour.
            corner=image[557:565,295:301]
            assert corner[...,3].min()>250
            assert corner[...,:3].max(-1).min()>210


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_pulled_cheek_does_not_hide_the_descending_blink(rig,face):
    from PIL import Image,ImageDraw
    r=Renderer(rig,1);s=Settings(expression=face)
    left=rig.cheek_images[face]['protect'].crop((0,0,520,rig.size[1]));box=left.getbbox()
    name=next(n for n in rig.face_parts(face) if rig.parts[n]['role']=='eye_l')
    pivot=rig.parts[name]['blink_pivot'][1]
    for scale in (.8,.55,.1):
        # Sweep the original window around the same documented lower-eye pivot;
        # compare real dark/colored eye pixels against an unpulled render.
        window=left.crop(box).resize((box[2]-box[0],max(1,round((box[3]-box[1])*scale))),Image.Resampling.NEAREST)
        mask=Image.new('L',rig.size)
        mask.paste(window,(box[0],round(pivot+(box[1]-pivot)*scale)-1))
        before=np.asarray(to_pil(r.render(s,Pose(head_y=-1,eye_scale=scale))))
        after=np.asarray(to_pil(r.render(s,Pose(head_y=-1,eye_scale=scale,pinch_delta=(-120,0)))))
        rgb=before[...,:3].astype(int)
        feature=(rgb.max(-1)<190)|((rgb[...,0]-rgb[...,1]>45)&(rgb[...,1]-rgb[...,2]>25))|((rgb[...,2]-rgb[...,0]>3)&(rgb.min(-1)<235))
        eye=(np.asarray(mask)>128)&feature
        assert eye.sum()>10
        assert np.array_equal(before[eye],after[eye])
