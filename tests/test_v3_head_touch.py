"""Head gestures, shared-rig ownership and full-frame restoration."""
from dataclasses import replace
import os

import numpy as np
import pytest

from v3proto.animation import Animator, Pose, Settings, SWAY_PARTS, AHOGE_GAIN
from v3proto.head_touch import (HeadParameters, HeadState, HeadGesture, knock_head,
                                stroke_head, release_head, step_head, pat_tilt)
from v3proto.head_scenarios import head_scenario
from v3proto.motion import transform_point


def quiet(**kwargs):
    return Settings(breath=False, blink=False, sway=False, **kwargs)


@pytest.mark.parametrize('gap,repeated', [(1.5, True), (1.500001, False)])
def test_knocks_use_adjacent_inclusive_gap_and_third_is_deterministic(gap, repeated):
    h = HeadState()
    for i in range(3):
        h = knock_head(h, i*gap, 'sleep', HeadParameters())
    assert h.face == 'teary'
    assert h.stage == ('protest' if repeated else 'knock')
    assert h.base == 'sleep'
    assert h.count == (0 if repeated else 1)


def test_protest_refresh_fade_and_streak_expiration():
    h = HeadState()
    for t in (0., .1, .2, 1.9):h = knock_head(h, t, 'neutral', HeadParameters())
    assert h.until == pytest.approx(3.9)
    assert step_head(h, 3.899, 0).stage == 'protest'
    fading = step_head(h, 4.075, 0)
    assert fading.stage == 'fade' and fading.fade == pytest.approx(.5)
    ended = step_head(h, 4.25, 0)
    assert not ended.active
    assert knock_head(ended, 4.3, 'neutral', HeadParameters()).count == 1


def test_pat_soothes_and_locks_parameters_until_next_interaction():
    p = HeadParameters()
    h = HeadState()
    for t in (0, .1, .2):h = knock_head(h, t, 'smug', p)
    h = stroke_head(h, .21, 12, 'angry', p)
    assert (h.face, h.base, h.count, h.last_knock) == ('happy', 'smug', 0, None)
    changed = replace(p, tilt=1.)
    h = stroke_head(h, .25, -2, 'angry', changed)
    assert h.params is p
    h = release_head(h, .3)
    assert release_head(h, .4) == h  # Repeated focus loss cannot extend it.
    assert not step_head(h, .3+p.after_hold+p.fade, 0).active
    assert stroke_head(HeadState(), 3, 1, 'smug', changed).params is changed


def test_follow_samples_do_not_depend_on_paint_frequency_and_return_exactly():
    h = stroke_head(HeadState(), 0., 1, 'smug', HeadParameters())
    for t in np.arange(.01, .12, .01):step_head(h, float(t), .01)
    assert step_head(h, .08, .08).head.position == pat_tilt(h, .08)
    h = stroke_head(h, .08, -1, 'smug', HeadParameters())
    assert -2.5 <= pat_tilt(h, .16) < 0
    assert pat_tilt(h, .33) == 0
    h = release_head(h, .16)
    assert pat_tilt(h, .16) < 0 and pat_tilt(h, .41) == pytest.approx(0)


@pytest.mark.parametrize('point,click,pat', [((6,0),True,False), ((7,0),False,False),
    ((11,0),False,False), ((12,0),False,True), ((0,50),False,False),
    ((4,4),True,False), ((5,5),False,False)])
def test_click_and_pat_logical_pixel_boundaries(point, click, pat):
    gesture = HeadGesture();gesture.press((0,0))
    gesture.move(point)
    assert gesture.patting == pat
    assert gesture.release() == click
    assert not gesture.active


def test_tiny_jitter_and_disabled_pat_do_not_start_or_continue_strokes():
    g = HeadGesture();g.press((0,0))
    for x in [3,-3]*30:assert g.move((x,0)) == 0
    assert g.release()
    g.press((0,0))
    assert g.move((100,0),False) == 0 and not g.release()
    g.press((0,0));assert g.move((12,0)) == 12
    assert g.move((13,0)) == 0
    assert g.move((14,0)) == 2


def test_head_and_pinch_handoffs_keep_geometry_base_and_secondary_pose():
    a = Animator(quiet(expression='sleep'))
    a.press((325,610));a.drag((205,610));a.advance(.4);a.release();before = a.advance(.02)
    delta, velocity = a.delta.copy(), a.velocity.copy()
    a.stroke_head(12);after = a.advance(0)
    assert after.reaction_face == 'happy' and after.reaction_base == 'sleep'
    assert after.body_scale == pytest.approx(before.body_scale)
    assert after.arm_degrees == pytest.approx(before.arm_degrees)
    assert after.head_roll == pytest.approx(before.head_roll)
    assert np.array_equal(a.delta,delta) and np.array_equal(a.velocity,velocity)
    assert not a.reaction.active
    a.advance(.02);head_before = a.pose
    a.press((325,610));after = a.advance(0)
    assert after.reaction_face == 'surprised' and after.reaction_base == 'sleep'
    assert after.arm_degrees == pytest.approx(head_before.arm_degrees)
    assert after.head_roll == pytest.approx(head_before.head_roll)
    assert not a.head_touch.active and np.array_equal(a.delta, a._drag_base)


def test_held_cheek_owns_input_and_old_reaction_never_reappears():
    a = Animator(quiet())
    a.press((325,610));a.advance(.3)
    a.knock_head();a.stroke_head(12)
    assert not a.head_touch.active and a.reaction.active
    a.release();a.stroke_head(12);a.release_head()
    a.advance(4)
    assert not a.interaction_active and a.pose.is_rest
    assert a.settings.expression == 'smug'


@pytest.mark.parametrize('kind', ['knock','pat'])
def test_switch_off_cancels_head_but_not_the_other_enable_setting(kind):
    s = quiet();a = Animator(s)
    if kind == 'knock':a.knock_head()
    else:a.stroke_head(12)
    assert a.interaction_active
    setattr(s,kind,False)
    assert a.advance(0).is_rest
    assert a.head_touch.count == 0 and not a.interaction_active


def test_head_uses_monotonic_stage_clock_after_a_stall():
    a = Animator(quiet(), now=100)
    a.knock_head(now=100)
    assert a.advance(.01, now=110).is_rest
    a.stroke_head(12, now=110)
    assert a.advance(.01, now=120).is_rest
    a.knock_head(now=120)
    assert a.head_touch.count == 1


@pytest.mark.parametrize('name',['knock','combo','pat-left','pat-right'])
def test_scenarios_restore_without_regular_animations_and_keep_bounds(name):
    a = Animator(quiet(pinch=False))
    p = head_scenario(a, name, .08 if name!='combo' else .58)
    assert p.reaction_face == ('teary' if name in ('knock','combo') else 'happy')
    assert .97 < p.body_scale < 1.01 and abs(p.head_roll) <= 2.5
    assert not head_scenario(Animator(quiet(pinch=False)),name,4).reaction_face


def test_head_hair_drive_stays_inside_existing_caps():
    s = Settings();a = Animator(s)
    for i in range(360):
        a.stroke_head(1 if i%60<30 else -1)
        p = a.advance(1/60)
        for n in SWAY_PARTS:
            assert abs(p.angles[n]) <= s.sway_degrees*(AHOGE_GAIN if n=='ahoge' else 1)+1e-9


@pytest.mark.parametrize('changes', [{'tilt':float('nan')},{'knock_count':2.5},
    {'return_time':.01},{'head_drop':90},{'protest':-1}])
def test_invalid_parameters_are_rejected(changes):
    with pytest.raises(ValueError):replace(HeadParameters(),**changes)


@pytest.fixture(scope='module')
def rig():
    from v3proto.render import Rig
    return Rig()


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_all_original_faces_restore_exactly_and_hair_is_preserved(rig,face):
    from v3proto.render import Renderer,premultiplied
    r = Renderer(rig,.4);s = quiet(expression=face,pinch=False)
    original = premultiplied(r.render(s,Pose()))
    for name in ('knock','combo','pat-left','pat-right'):
        a = Animator(s);head_scenario(a,name,.58)
        r.render(s,a.pose)
        a.advance(5)
        assert a.pose.is_rest and s.expression == face
        assert np.array_equal(original,premultiplied(r.render(s,a.pose)))
    # New reactions reuse the repaired erasure/composition, without altering hair.
    p = Pose(reaction_face='happy',reaction_base=face)
    plain = premultiplied(r.head_surface.render(s,Pose()))
    reaction = premultiplied(r.head_surface.render(s,p))
    yy,xx=np.indices(plain.shape[:2]);xx=xx/.4+r.head_surface.x;yy=yy/.4+r.head_surface.y
    outside=(xx<290)|(xx>755)|(yy<385)|(yy>625)
    assert np.array_equal(plain[outside],reaction[outside])


def test_crown_hit_uses_same_inverse_mesh_and_excludes_face_and_cheek(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4);s=Settings()
    for angle in (-2.5,0,2.5):
        p=Pose(head_roll=angle,head_y=-3)
        source=np.array([500.,150.]);root=np.array(rig.pivots['neck'])
        theta=np.deg2rad(angle);c,v=np.cos(theta),np.sin(theta)
        world=root+[[c,-v],[v,c]]@(source-root)+[0,-3]
        assert r.hit_test(world,s,p,crown=True)[0]=='crown'
    assert r.hit_test((530,580),s,Pose(),crown=True)[0]=='face'
    assert r.hit_test((325,610),s,Pose(),crown=True)[0]=='cheek'
    assert r.hit_test((0,0),s,Pose(),crown=True)[0] is None


def test_head_bones_leave_feet_and_shoulders_fixed(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4)
    base=r.matrices(Pose(body_scale=.99))
    actual=r.matrices(Pose(body_scale=.99,head_roll=2.5,head_y=4,arm_degrees=3))
    for leg in ('leg_l','leg_r'):assert np.array_equal(base[leg],actual[leg])
    for arm in ('arm_l','arm_r'):
        pivot=rig.pivots[rig.parts[arm]['pivot']]
        assert transform_point(base[arm],pivot)==pytest.approx(transform_point(actual[arm],pivot))


@pytest.fixture
def window(rig):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from v3proto.window import Preview
    app=QApplication.instance() or QApplication([])
    w=Preview(rig,quiet())
    w.canvas.timer.stop();w.stats_timer.stop()
    yield w
    w.close();app.processEvents()


def input_event(x,y,button=None):
    from PySide6.QtCore import QPointF,Qt
    class Event:
        def position(self):return QPointF(x,y)
        def button(self):return button or Qt.MouseButton.LeftButton
    return Event()


def test_window_double_click_is_two_knocks_and_hover_is_passive(window):
    c=window.canvas;ox,oy=c.image_origin;e=input_event(ox+500*.4,oy+150*.4)
    c.mouseMoveEvent(e)
    assert not c.animator.interaction_active
    c.mousePressEvent(e);c.mouseReleaseEvent(e)
    c.mouseDoubleClickEvent(e);c.mouseReleaseEvent(e)
    assert c.animator.head_touch.count==2
    c.mousePressEvent(e);c.mouseReleaseEvent(e)
    assert c.animator.head_touch.face=='teary' and c.animator.head_touch.stage=='protest'
    assert not window.combo.isEnabled()


@pytest.mark.parametrize('scale',[.25,.4,.6])
def test_gesture_threshold_stays_in_logical_pixels_at_display_scales(window,scale):
    c=window.canvas;c.display_scale=scale
    ox,oy=c.image_origin;x,y=ox+500*scale,oy+150*scale
    c.mousePressEvent(input_event(x,y))
    c.mouseMoveEvent(input_event(x+11,y))
    assert not c.animator.head_touch.active
    c.mouseMoveEvent(input_event(x+12,y))
    assert c.animator.head_touch.face=='happy'
    c.mouseReleaseEvent(input_event(x+12,y))
    assert c.animator.head_touch.count==0 and not c.head_gesture.active


def test_focus_loss_clears_pending_press_without_knock_and_releases_pat(window):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    c=window.canvas;ox,oy=c.image_origin;x,y=ox+200,oy+60
    c.mousePressEvent(input_event(x,y))
    c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert not c.animator.interaction_active and not c.head_gesture.active
    c.mousePressEvent(input_event(x,y));c.mouseMoveEvent(input_event(x+20,y))
    c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    released=c.animator.head_touch.released_at
    c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert released is not None and c.animator.head_touch.released_at==released


def test_panel_parameter_snapshot_reset_and_disable(window):
    from PySide6.QtWidgets import QDoubleSpinBox
    knobs={key:widget for widget,key,_ in window.controls if isinstance(widget,QDoubleSpinBox)}
    knobs['head_touch.tilt'].setValue(2)
    a=window.canvas.animator;a.stroke_head(12);window.update_reaction()
    assert not window.combo.isEnabled()
    knobs['head_touch.tilt'].setValue(1)
    a.stroke_head(12)
    assert a.head_touch.params.tilt==2
    window.reset()
    assert window.settings.head_touch==HeadParameters() and window.combo.isEnabled()
    a=window.canvas.animator;a.knock_head();window.change('knock',False)
    assert not a.head_touch.active and a.pose.reaction_face is None and a.pose.head_roll == 0


@pytest.mark.parametrize('name',['knock','combo','pat-left','pat-right'])
def test_cli_snapshot_uses_v3_renderer_with_head_scenario(rig,tmp_path,name):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from v3proto.__main__ import main
    out=tmp_path/(name+'.png')
    assert main(['--snapshot',str(out),'--head-preview',name,'--time','.58','--no-animation'])==0
    assert out.stat().st_size>1000
