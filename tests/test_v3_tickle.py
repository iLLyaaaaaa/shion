"""Belly gesture boundaries, reaction ownership, continuous rig and UI routing."""
from dataclasses import replace
import os

import numpy as np
import pytest

from v3proto.animation import Animator, Pose, Settings
from v3proto.motion import transform_point, pivot_matrix
from v3proto.tickle import (BellyGesture, TickleState, stroke_tickle, release_tickle,
                            step_tickle, STOP_DELAY, TORSO_PIVOT, NECK_PIVOT)


def quiet(**kwargs):
    return Settings(breath=False,blink=False,sway=False,**kwargs)


def rub(gesture, start=0.):
    return [gesture.move((x,0.),start+t) for t,x in ((.1,8),(.2,0),(.3,8))]


def test_exact_eight_pixel_reversals_and_two_reverse_trigger():
    g=BellyGesture();g.press((0,0))
    assert rub(g)==[None,None,'tickle']
    assert g.tickling and len(g.reversals)==2
    assert g.move((9,0),.4) is None
    assert g.move((10,0),.5)=='tickle'
    g.clear();assert not g.active and not g.tickling


def test_confirmed_reverse_starts_immediately_despite_subpixel_last_event():
    g=BellyGesture();g.press((0,0))
    for i,x in enumerate((8.3,6.3,4.3,2.3,.3,.2,2.3,4.3,6.3)):
        assert g.move((x,0),i*.05) is None
    assert g.move((8.2001,0),.5)=='tickle'


@pytest.mark.parametrize('offset,action',[(40,None),(40.001,None),(-40,None),(-40.001,None)])
def test_forty_logical_pixel_lift_boundary(offset,action):
    g=BellyGesture();g.press((0,0))
    assert g.move((offset,0),.1)==action


@pytest.mark.parametrize('last,active',[(1.7,True),(1.70001,False)])
def test_reverse_window_boundary(last,active):
    g=BellyGesture();g.press((0,0))
    g.move((8,0),.1);g.move((0,0),.2)
    assert (g.move((8,0),last)=='tickle')==active


@pytest.mark.parametrize('points',[
    [(0,i%20) for i in range(40)],
    [(i%3,0) for i in range(40)],
    [(i,0) for i in range(40)],
    [(7 if i%2 else 0,0) for i in range(40)],
])
def test_vertical_jitter_short_reversals_and_one_way_are_quiet(points):
    g=BellyGesture();g.press((0,0))
    assert all(g.move(p,i*.05) is None for i,p in enumerate(points))
    assert not g.tickling


def test_stop_and_release_use_real_time_not_animation_dt():
    a=Animator(quiet());a.tickle_belly(now=0)
    a.advance(.1,now=.1);assert a.tickle.stage=='tickle'
    a.advance(.01,now=STOP_DELAY);assert a.tickle.stage=='settle'
    a.advance(.01,now=10)
    assert not a.interaction_active and a.pose.is_rest
    a.tickle_belly(now=11);a.release_tickle(now=11.1);a.release_tickle(now=11.2)
    assert a.tickle.released_at==11.1
    a.advance(.01,now=13);assert a.pose.is_rest


@pytest.mark.parametrize('face',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_tickle_restores_original_expression(face):
    a=Animator(quiet(expression=face));a.tickle_belly();a.advance(.1)
    assert a.pose.reaction_face=='happy' and a.settings.expression==face
    assert abs(a.pose.body_roll)<2 and a.pose.head_x!=0
    a.release_tickle();a.advance(2)
    assert a.pose.is_rest and a.original_expression==face


def test_transfer_to_lift_is_continuous_and_preserves_original():
    a=Animator(quiet(expression='sleep'));a.knock_head();a.advance(.1)
    a.tickle_belly();a.advance(.1)
    old=a.pose
    assert not a._star_bursts and a.tickle.base=='sleep'
    a.begin_lift((543,880));a.advance(0)
    for name in ('body_roll','head_x','head_y','head_roll','arm_degrees','body_scale'):
        assert getattr(a.pose,name)==pytest.approx(getattr(old,name),abs=1e-6)
    assert a.lift.base=='sleep' and not a.tickle.owns_face
    a.move_lift((80,-120),32);a.advance(.1);a.release_lift();a.advance(4)
    assert a.pose.is_rest and a.original_expression=='sleep'


@pytest.mark.parametrize('action',['pat','knock','pinch'])
def test_new_touch_takes_face_and_old_tickle_does_not_resume(action):
    a=Animator(quiet(expression='neutral'));a.tickle_belly();a.advance(.1);a.release_tickle()
    if action=='pat':a.stroke_head(12)
    elif action=='knock':a.knock_head()
    else:a.press((325,610))
    a.advance(.01)
    assert not a.tickle.owns_face
    assert a.pose.reaction_base=='neutral'
    assert a.pose.reaction_face=={'pat':'happy','knock':'teary','pinch':'surprised'}[action]
    a.release();a.release_head();a.advance(5)
    assert a.pose.is_rest


def test_disable_underlays_and_expression_change_end_tickle():
    a=Animator(quiet());a.tickle_belly();a.advance(.1)
    a.settings.tickle=False;a.advance(.01)
    assert a.tickle.released_at is not None
    a.advance(2);assert a.pose.is_rest
    a.settings.tickle=True;a.tickle_belly();a.settings.expression='neutral';a.advance(0)
    assert a.pose.is_rest and not a.tickle.active
    a.tickle_belly();a.settings.underlays_only=True;a.advance(0)
    assert not a.tickle.active


@pytest.fixture(scope='module')
def rig():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from v3proto.render import Rig
    app=QApplication.instance() or QApplication([])
    yield Rig()


def test_belly_is_visible_torso_only_and_wriggle_inverse_matches(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4);s=quiet()
    assert r.hit_test((543,880),s,Pose(),belly=True)[0]=='belly'
    for point in ((543,1010),(325,610),(500,150),(250,850),(543,1200)):
        assert r.hit_test(point,s,Pose(),belly=True)[0]!='belly'
    a=Animator(s);a.tickle_belly();a.advance(.1);p=a.pose
    matrices=r.matrices(p)
    for leg in ('leg_l','leg_r'):assert np.array_equal(matrices[leg],np.eye(3))
    torso=transform_point(matrices['body'],(543,880))
    assert r.hit_test(torso,s,p,belly=True)[0]=='belly'
    assert transform_point(matrices['head_skin'],NECK_PIVOT)==pytest.approx(
        transform_point(matrices['body'],NECK_PIVOT),abs=1e-6)
    for point in ((325,610),(500,150)):
        world=transform_point(matrices['head_skin'],point)
        assert r.hit_test(world,s,p,crown=True)[0]==r.hit_test(point,s,Pose(),crown=True)[0]


@pytest.mark.parametrize('scale,dpr',[(.25,1),(.4,1),(.4,2),(.6,1)])
def test_canvas_rub_lift_transition_and_no_release_knock(rig,scale,dpr,monkeypatch):
    from v3proto.window import Preview
    from v3proto.render import Renderer
    from tests.test_v3_head_touch import input_event
    clock=[10.]
    monkeypatch.setattr('v3proto.window.time.perf_counter',lambda:clock[0])
    w=Preview(rig,quiet(),scale);c=w.canvas
    c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    c.renderer=Renderer(rig,scale*dpr)
    ox,oy=c.image_origin;x,y=ox+543*scale,oy+880*scale
    try:
        e=input_event(x,y);c.mouseMoveEvent(e);assert not c.animator.interaction_active
        c.mousePressEvent(e)
        for i,dx in enumerate((8,0,8)):
            clock[0]=10.1+i*.1;c.mouseMoveEvent(input_event(x+dx,y))
        assert c.animator.tickle.active and c.animator.pose.reaction_face=='happy'
        assert not c.animator.lift.active and not w.combo.isEnabled()
        old=c.animator.pose.root_offset
        clock[0]=10.4;c.mouseMoveEvent(input_event(x+40,y))
        assert not c.animator.lift.held
        clock[0]=10.5;c.mouseMoveEvent(input_event(x+40.1,y))
        assert not c.animator.lift.held and c.belly_gesture.active
        assert c.animator.pose.root_offset==old
        clock[0]=10.6;c.mouseMoveEvent(input_event(x+45.1,y-10))
        assert c.animator.pose.root_offset==pytest.approx((0,0))
        c.mouseReleaseEvent(input_event(x+45.1,y-10))
        assert not c.animator.lift.held and c.animator.head_touch.count==0
        c.animator.advance(5);assert c.animator.pose.is_rest
    finally:w.close()


def test_focus_loss_pending_click_and_panel_reset(rig):
    from v3proto.window import Preview
    from tests.test_v3_head_touch import input_event
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtCore import QEvent
    w=Preview(rig,quiet());c=w.canvas;c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    ox,oy=c.image_origin;e=input_event(ox+543*.4,oy+880*.4)
    try:
        c.mousePressEvent(e);c.mouseReleaseEvent(e);c.mouseDoubleClickEvent(e);c.mouseReleaseEvent(e)
        assert not c.animator.interaction_active
        c.mousePressEvent(e);c.animator.tickle_belly();c.animator.advance(.1)
        c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        at=c.animator.tickle.released_at;c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        assert at is not None and c.animator.tickle.released_at==at and not c.belly_gesture.active
        w.reset();assert c.animator.pose.is_rest and not c.belly_gesture.active and w.combo.isEnabled()
    finally:w.close()


@pytest.mark.parametrize('name',['rub','release','lift'])
def test_snapshot_cli_and_scenario_ends(rig,tmp_path,name):
    from v3proto.__main__ import main
    from v3proto.tickle_scenarios import tickle_scenario
    out=tmp_path/(name+'.png')
    assert main(['--snapshot',str(out),'--tickle-preview',name,'--time','.8','--no-animation'])==0
    assert out.stat().st_size>1000
    a=Animator(quiet());p=tickle_scenario(a,name,5)
    assert p.is_rest


def test_tickle_cli_requires_snapshot_and_is_exclusive(rig):
    from v3proto.__main__ import main
    for args in (['--tickle-preview','rub'],['--snapshot','unused.png','--tickle-preview','rub','--head-preview','knock'],
                 ['--benchmark','1','--benchmark-lift','--benchmark-tickle']):
        with pytest.raises(SystemExit):main(args)
