"""Independent pinch reaction timing, continuity and real-render contracts."""
from dataclasses import replace
import os
import numpy as np
import pytest

from v3proto.animation import Animator, Pose, Settings
from v3proto.reaction import (ReactionParameters, ReactionState, press_reaction,
                               release_reaction, step_reaction)


def test_surprise_finishes_before_latched_threshold_and_release_can_interrupt():
    p=ReactionParameters()
    s=press_reaction(ReactionState(),0,'happy',p)
    s=step_reaction(s,.1,.1,.9)
    assert (s.stage,s.face,s.escalated)==('surprise','surprised',True)
    s=step_reaction(s,.21,.01,0)
    assert (s.stage,s.face)==('cry','teary')
    s=release_reaction(s,.22)
    assert (s.stage,s.face)==('rebound','angry')
    early=release_reaction(press_reaction(ReactionState(),0,'sleep',p),.01)
    assert early.face=='angry'


def test_hold_threshold_is_strict_and_escalation_is_latched():
    p=ReactionParameters()
    s=press_reaction(ReactionState(),0,'smug',p)
    s=step_reaction(s,.2,.01,.7)
    assert s.stage=='struggle'
    assert step_reaction(s,2,.01).stage=='struggle'
    s=step_reaction(s,2.001,.001)
    assert s.stage=='cry'
    assert step_reaction(s,2.1,.01,0).stage=='cry'


def test_rolling_window_third_and_later_and_window_boundary():
    p=ReactionParameters()
    s=ReactionState()
    for i in range(4):
        s=press_reaction(s,float(i),'happy',p)
        assert s.easter==(i>=2)
        assert s.face==('teary' if i>=2 else 'surprised')
        s=release_reaction(s,i+.1)
        assert s.face==('teary' if i>=2 else 'angry')
    s=press_reaction(s,12,'happy',p)
    assert s.count==3 and s.easter
    s=press_reaction(s,22.001,'happy',p)
    assert s.count==1 and not s.easter


def test_hold_fade_timing_and_original_base_survives_regrab():
    p=ReactionParameters()
    s=press_reaction(ReactionState(),0,'sleep',p)
    s=release_reaction(s,.1)
    s=step_reaction(s,.2,.01,settled=True)
    assert s.stage=='hold' and s.settled_at==.2
    assert step_reaction(s,1.699,.01).stage=='hold'
    fading=step_reaction(s,1.875,.01)
    assert fading.stage=='fade' and fading.fade==pytest.approx(.5)
    grabbed=press_reaction(fading,1.88,'angry',p)
    assert grabbed.base=='sleep' and grabbed.fade==0
    assert not step_reaction(s,2.1,.01).active


def test_parameter_snapshot_is_immutable_and_reset_clears_combo():
    settings=Settings(breath=False,blink=False,sway=False)
    a=Animator(settings)
    a.press((325,610))
    settings.reaction=replace(settings.reaction,cry_after=.3)
    assert a.advance(.5).reaction_face=='dizzy'
    a.release();a.press((325,610));a.advance(.5)
    assert a.pose.reaction_face=='teary'
    settings.pinch=False
    assert a.advance(0).is_rest
    assert not a.reaction.history


def test_regrab_preserves_geometry_and_monotonic_windows_after_stall():
    a=Animator(Settings(breath=False,blink=False,sway=False))
    a.press((325,610));a.drag((245,610));a.advance(.3);a.release()
    a.advance(.05);delta=a.delta.copy()
    a.press((315,610));a.drag((315,610))
    assert a.delta==pytest.approx(delta)
    assert a.reaction.base=='smug' and a.reaction.count==2
    a.advance(.01,now=30.)
    a.release();a.press((315,610))
    assert a.reaction.count==1 and not a.reaction.easter


def test_body_arms_and_rebound_head_are_bounded_and_smooth():
    a=Animator(Settings(breath=False,blink=False,sway=False))
    a.press((325,610));body=[];arms=[];head=[]
    for i in range(720):
        if i==40:a.drag((205,610))
        if i==300:a.release()
        pose=a.advance(1/120)
        body.append(pose.body_scale);arms.append(pose.arm_degrees);head.append(pose.head_roll)
    assert .98<min(body)<.999 and max(body)<1.002
    assert max(abs(x) for x in arms)>2
    assert max(abs(x) for x in arms)<5
    assert max(abs(x) for x in head)>.1
    assert max(abs(x) for x in head)<1.3
    assert max(abs(x) for x in np.diff(arms))<1.8
    assert max(abs(x) for x in np.diff(head))<.15
    a.advance(5)
    assert not a.reaction.active and a.pose.is_rest


@pytest.fixture(scope='module')
def rig():
    from v3proto.render import Rig
    return Rig()


def test_shoulder_pivots_and_feet_stay_fixed(rig):
    from v3proto.render import Renderer
    from v3proto.motion import transform_point
    r=Renderer(rig)
    base=r.matrices(Pose(body_scale=.985))
    actual=r.matrices(Pose(body_scale=.985,arm_degrees=4.5,head_roll=1))
    for arm in ('arm_l','arm_r'):
        pivot=rig.pivots[rig.parts[arm]['pivot']]
        assert transform_point(actual[arm],pivot)==pytest.approx(transform_point(base[arm],pivot))
        assert not np.array_equal(actual[arm],base[arm])
    assert np.array_equal(actual['leg_l'],np.eye(3))


def test_reaction_without_regular_animations_is_visible_and_restores_exactly(rig):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,.4)
    for face in rig.faces:
        settings=Settings(expression=face,breath=False,blink=False,sway=False)
        a=Animator(settings)
        before=premultiplied(r.render(settings,Pose()))
        a.press((325,610));p=a.advance(.1)
        assert p.reaction_face=='surprised' and not p.is_rest
        assert not np.array_equal(before,premultiplied(r.render(settings,p)))
        a.release();p=a.advance(6)
        assert p.is_rest
        assert np.array_equal(before,premultiplied(r.render(settings,p)))
        assert settings.expression==face


def test_reaction_keeps_hair_pixels_and_dizzy_has_no_external_stars(rig):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,.6)
    for face in rig.faces:
        s=Settings(expression=face)
        a=premultiplied(r.head_surface.render(s,Pose()))
        p=Pose(reaction_face='dizzy',reaction_base=face)
        b=premultiplied(r.head_surface.render(s,p))
        yy,xx=np.indices(a.shape[:2]);xx=xx/.6+r.head_surface.x;yy=yy/.6+r.head_surface.y
        outside=(xx<290)|(xx>755)|(yy<385)|(yy>625)
        assert np.array_equal(a[outside],b[outside])


def test_head_roll_hit_inverse_matches_same_mesh(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.6);s=r.head_surface
    for angle in (-1.2,1.2):
        p=Pose(head_roll=angle,head_y=-4)
        root=np.array(rig.pivots['neck'])
        theta=np.deg2rad(angle);c,v=np.cos(theta),np.sin(theta)
        point=np.array([325.,610.]);delta=point-root
        world=root+np.array([c*delta[0]-v*delta[1],v*delta[0]+c*delta[1]])+[0,-4]
        assert s.source_point(world,p)==pytest.approx(point,abs=.001)


def test_panel_snapshot_defaults_and_cancellation(rig):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QDoubleSpinBox
    from v3proto.window import Preview
    app=QApplication.instance() or QApplication([])
    w=Preview(rig,Settings())
    try:
        w.canvas.timer.stop()
        controls={k:v for v,k,_ in w.controls if isinstance(v,QDoubleSpinBox)}
        controls['reaction.surprise'].setValue(.45)
        w.canvas.animator.press((325,610));w.update_reaction()
        assert not w.combo.isEnabled()
        controls['reaction.surprise'].setValue(.55)
        assert w.canvas.animator.reaction.params.surprise==.45
        w.reset()
        assert controls['reaction.surprise'].value()==.2
        assert w.settings.reaction.surprise==.2
        assert w.combo.isEnabled()
        assert not w.canvas.animator.reaction.history
    finally:w.close();app.processEvents()


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_static_fade_handoff_does_not_switch_whole_artwork(rig,face):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,.4)
    settings=Settings(expression=face,breath=False,blink=False,sway=False)
    expected=premultiplied(r.render(settings,Pose())).astype(int)
    p=Pose(reaction_face='angry',reaction_base=face,reaction_fade=1-1e-8)
    actual=premultiplied(r.render(settings,p)).astype(int)
    assert np.abs(actual-expected).max()<=1


def test_repeated_focus_release_does_not_stop_an_existing_rebound():
    a=Animator(Settings());a.press((325,610));a.drag((205,610));a.release()
    a.advance(.1);velocity=a.velocity.copy()
    a.release()
    assert np.array_equal(a.velocity,velocity)


def test_custom_rebound_speed_and_zero_surprise():
    p=replace(ReactionParameters(),surprise=0,rebound_time=2)
    assert press_reaction(ReactionState(),0,'neutral',p).face=='dizzy'
    a=Animator(Settings(reaction=p));b=Animator(Settings())
    for actor in (a,b):
        actor.press((325,610));actor.drag((205,610));actor.release()
    a.advance(.1);b.advance(.05)
    assert a.delta==pytest.approx(b.delta,abs=1e-9)


def test_cancel_and_reset_restore_original_expression(rig):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from v3proto.window import Preview
    app=QApplication.instance() or QApplication([])
    w=Preview(rig,Settings(expression='happy'))
    try:
        w.canvas.timer.stop()
        w.canvas.animator.press((325,610));w.canvas.animator.advance(.4)
        w.reset()
        assert w.settings.expression=='happy'
        assert w.combo.currentData()=='happy'
        assert not w.canvas.animator.reaction.active
        w.canvas.animator.press((325,610));w.canvas.animator.advance(.4)
        w.change('pinch',False)
        assert w.settings.expression=='happy' and not w.canvas.animator.reaction.active
    finally:w.close();app.processEvents()


def test_feature_fade_is_continuous_with_ordinary_motion(rig):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,.4);s=Settings(expression='sleep')
    p=Pose(head_y=-2,pinch_delta=(0,0),reaction_face='angry',reaction_base='sleep',reaction_fade=.5)
    a=premultiplied(r.render(s,p)).astype(int)
    b=premultiplied(r.render(s,replace(p,reaction_fade=.5+1e-6))).astype(int)
    assert np.abs(a-b).max()<=1
    base=premultiplied(r.render(s,Pose(head_y=-2))).astype(int)
    end=premultiplied(r.render(s,replace(p,reaction_fade=1-1e-8))).astype(int)
    assert np.abs(base-end).max()<=1


@pytest.mark.parametrize('reaction_face',['surprised','dizzy','teary','angry'])
def test_reaction_features_are_fixed_during_pull_and_blink(rig,reaction_face):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,.6);s=Settings(expression='neutral',pinch_maximum=200)
    for eyes in (1,.55,.1):
        p=Pose(head_y=-1,eye_scale=eyes,reaction_face=reaction_face,reaction_base='neutral')
        # Deep inside opaque glyphs every pixel belongs to the fixed features,
        # including tears compressed below the original eye window.
        mask=r.head_surface.reaction_face.feature_mask(reaction_face,eyes)
        from PIL import Image
        full=Image.new('L',r.head_surface.reference_size)
        origin=rig.face_plate[1]
        full.paste(mask,(origin[0]-r.head_surface.x,origin[1]-r.head_surface.y))
        mask=np.asarray(full.resize((r.head_surface.w,r.head_surface.h),Image.Resampling.LANCZOS))
        image=r.head_surface.compose(s,replace(p,head_y=0))
        image2=r.head_surface.compose(s,replace(p,head_y=0,pinch_delta=(-200,-24)))
        assert np.array_equal(image[mask==255],image2[mask==255])


def test_smug_source_eyelid_is_not_left_above_the_teary_reaction(rig):
    from v3proto.render import Renderer
    surface=Renderer(rig,1).head_surface
    pixels=surface.compose(Settings(expression='smug'),Pose(reaction_face='teary'))
    for x,y in ((653,435),(665,437),(657,439),(647,441),(681,447)):
        color=pixels[y-surface.y,x-surface.x]
        assert color[3]==255 and color[:3].min()>200,(x,y,color)


@pytest.mark.parametrize('reaction_face',['surprised','dizzy','teary','angry'])
def test_reaction_plate_feather_never_punches_alpha_holes_in_hair(rig,reaction_face):
    from v3proto.render import Renderer
    surface=Renderer(rig,.6).head_surface
    for face in rig.faces:
        settings=Settings(expression=face)
        before=surface.compose(settings,Pose())
        after=surface.compose(settings,Pose(reaction_face=reaction_face))
        opaque=before[...,3]==255
        assert (after[...,3][opaque]==255).all(),face


@pytest.mark.parametrize('face',['smug','neutral','teary'])
def test_inward_rebound_does_not_leave_the_old_cheek_contour(rig,face):
    from v3proto.render import Renderer
    surface=Renderer(rig,1).head_surface
    for dx in (6,12):
        pixels=surface.compose(Settings(expression=face),Pose(pinch_delta=(dx,0),reaction_face='teary'))
        for x,y in ((278,600),(280,615),(286,630)):
            # Probe the old stroke's outside edge, not the middle where the
            # legitimately moved 11-pixel stroke can still overlap.
            if face=='neutral':x-=4
            color=pixels[y-surface.y,x-surface.x]
            assert not (color[3]>128 and color[:3].max()<160),(face,dx,x,y,color)


def test_cut_removes_the_outline_owners_in_bangs_and_side_hair(rig):
    from v3proto.render import Renderer
    surface=Renderer(rig,1).head_surface
    cut=np.asarray(surface._compose_image(Settings(expression='smug'),Pose(),True))
    for x,y in ((282,600),(285,615),(292,630)):
        assert cut[y-surface.y,x-surface.x,3]==0
