"""Lift routing, continuous transforms, real-time return and reaction ownership."""
from dataclasses import replace
import os

import numpy as np
import pytest

from v3proto.animation import Animator, Pose, Settings
from v3proto.lift import (BodyGesture, LiftState, begin_lift, move_lift, release_lift,
                          step_lift, root_matrix, RETURN_TIME, SCENE_PADDING)
from v3proto.motion import transform_point


def quiet(**kwargs):
    return Settings(breath=False,blink=False,sway=False,**kwargs)


@pytest.mark.parametrize('delta,starts',[(6,False),(6.001,True),(-6,False),(-6.001,True)])
def test_six_logical_pixel_slop(delta,starts):
    g=BodyGesture();g.press((10,20),(500,800),(0,0))
    assert g.move((10+delta,20))==starts
    g.move((10,20))
    assert g.started==starts
    g.clear();assert not g.active


def test_three_real_reversals_dizzy_and_hold_is_not_shaking():
    s=begin_lift(LiftState(),0,'neutral',(543,790),Pose())
    for t,x in ((.1,40),(.2,17),(.3,40),(.4,16),(.5,40)):
        s=move_lift(s,(x,0),x,t)
    assert len(s.shakes)==2 and not s.dizzy  # 23 px reverse did not count.
    s=move_lift(s,(16,0),16,.6)
    assert s.dizzy and len(s.shakes)==3
    assert step_lift(s,10).face=='dizzy'


@pytest.mark.parametrize('samples',[
    [(i*.1,i*10) for i in range(20)],
    [(i*.1,(i%2)*3) for i in range(20)],
    [(0.1,40),(3,0),(6,40),(9,0)],
])
def test_monotone_jitter_and_slow_reversals_do_not_dizzy(samples):
    s=begin_lift(LiftState(),0,'smug',(543,790),Pose())
    for t,x in samples:s=move_lift(s,(x,-50),x,t)
    assert not step_lift(s,10).dizzy


def test_return_uses_wall_clock_and_repeated_release_keeps_trajectory():
    a=Animator(quiet());a.begin_lift((543,790),now=0)
    a.move_lift((160,-180),64,now=.2);a.advance(.2)
    a.release_lift(now=.4);a.advance(0)
    before=a.pose.root_offset
    assert before==pytest.approx((160,-180))
    a.release_lift(now=.5)
    assert a.lift.released_at==.4
    a.advance(.01,now=.4+RETURN_TIME+.01)
    assert a.pose.root_offset==(0,0) and a.pose.root_roll==0
    a.advance(.01,now=10)
    assert not a.interaction_active and a.pose.is_rest


def test_stop_pointer_returns_tilt_and_clamps_translation():
    a=Animator(quiet());a.begin_lift((543,790),now=0)
    a.move_lift((2000,-2000),80,now=.2)
    a.advance(.2,now=.3)
    assert a.pose.root_offset==(240,-220) and abs(a.pose.root_roll)<=8
    a.advance(.9,now=1.2)
    assert abs(a.pose.root_roll)<.15 and a.lift.held


def test_regrab_and_touch_takeover_keep_original_expression_and_root():
    a=Animator(quiet(expression='sleep'))
    a.knock_head();a.advance(.1)
    a.begin_lift((543,790));assert a.lift.base=='sleep' and not a.head_touch.active
    a.move_lift((90,-150),36);a.advance(.1);a.release_lift()
    a.advance(.1);old=a.pose.root_offset
    a.begin_lift((600,900));a.advance(0)
    assert a.pose.root_offset==pytest.approx(old) and a.lift.base=='sleep'
    a.release_lift();a.stroke_head(12);a.advance(0)
    assert a.pose.reaction_face=='happy' and a.head_touch.base=='sleep'
    assert a.pose.root_offset==pytest.approx(old)
    a.advance(5)
    assert a.pose.is_rest and a.settings.expression=='sleep'


def test_held_lift_owns_face_disable_returns_and_expression_reset_cancels():
    a=Animator(quiet());a.begin_lift((543,790));a.move_lift((100,-100),40)
    a.press((325,610));a.knock_head();a.stroke_head(12)
    assert a.lift.held and not a.dragging and not a.head_touch.active
    a.settings.lift=False;a.advance(.01)
    assert a.lift.released_at is not None
    a.advance(3);assert not a.interaction_active
    a.settings.lift=True;a.begin_lift((543,790));a.settings.expression='happy';a.advance(0)
    assert not a.lift.active and a.pose.is_rest


@pytest.fixture(scope='module')
def rig():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from v3proto.render import Rig
    app=QApplication.instance() or QApplication([])
    yield Rig()


def test_painted_root_and_inverse_hits_use_same_transform(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4);s=quiet();p=Pose(root_offset=(120,-150),root_roll=7)
    for point in ((543,790),(325,610),(500,150)):
        expected=r.hit_test(point,s,Pose(),crown=True)[0]
        world=transform_point(root_matrix(p),point)
        hit,local=r.hit_test(world,s,p,crown=True)
        assert hit==expected
        assert r.rig_point(world,p)==pytest.approx(point)
    for leg in ('leg_l','leg_r'):
        pivot=rig.pivots[rig.parts[leg]['pivot']]
        assert transform_point(r.matrices(Pose(leg_degrees=3))[leg],pivot)==pytest.approx(pivot)
    im=r.render(s,p,padding=SCENE_PADDING)
    assert im.width()==round((rig.size[0]+SCENE_PADDING[0]+SCENE_PADDING[2])*.4)
    # A transformed opaque body point must land in the image at its visible position.
    x,y=transform_point(root_matrix(p),(543,850))
    assert im.pixelColor(round((x+SCENE_PADDING[0])*.4),round((y+SCENE_PADDING[1])*.4)).alpha()>64


@pytest.mark.parametrize('scale',[.25,.4,.6])
def test_canvas_body_threshold_head_isolation_and_focus_release(rig,scale):
    from v3proto.window import Preview
    from tests.test_v3_head_touch import input_event
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    w=Preview(rig,quiet(),scale)
    c=w.canvas;c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    ox,oy=c.image_origin;x,y=ox+325*scale,oy+610*scale
    try:
        c.mouseMoveEvent(input_event(x,y));assert not c.animator.interaction_active
        c.mousePressEvent(input_event(x,y));c.mouseMoveEvent(input_event(x+6,y))
        assert not c.animator.lift.active
        c.mouseMoveEvent(input_event(x+6.1,y-20));assert c.animator.lift.held
        assert c.animator.pose.root_offset==pytest.approx((0,0))
        c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        at=c.animator.lift.released_at
        c.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        assert at is not None and c.animator.lift.released_at==at and not c.body_gesture.active
        c.animator.advance(5)
        e=input_event(ox+500*scale,oy+150*scale)
        c.mousePressEvent(e);c.mouseMoveEvent(input_event(e.position().x()+100,e.position().y()))
        assert not c.animator.lift.active and c.animator.head_touch.face=='happy'
        c.mouseReleaseEvent(e)
    finally:w.close()


@pytest.mark.parametrize('scenario',['held','shake','release'])
def test_lift_snapshot_cli(rig,tmp_path,scenario):
    from v3proto.__main__ import main
    out=tmp_path/(scenario+'.png')
    assert main(['--snapshot',str(out),'--lift-preview',scenario,'--time','1.5','--no-animation'])==0
    assert out.stat().st_size>1000


def test_scenario_frame_times_are_nonnegative_and_restore_after_release():
    from v3proto.lift_scenarios import lift_scenario
    for i in range(121):
        a=Animator(quiet())
        lift_scenario(a,'release',i/24)
        if i/24 > 3.1:assert not a.lift.active and a.pose.is_rest


@pytest.mark.parametrize('expression',['smug','neutral','happy','surprised','teary','angry','sleep','dizzy'])
def test_all_original_expressions_restore(expression):
    a=Animator(quiet(expression=expression));a.begin_lift((543,790));a.move_lift((90,-100),36)
    a.advance(.3);a.release_lift();a.advance(4)
    assert a.settings.expression==expression and a.pose.is_rest


def test_pending_regrab_uses_current_return_position_and_body_clicks_are_inert(rig):
    from v3proto.window import Preview
    from tests.test_v3_head_touch import input_event
    w=Preview(rig,quiet());c=w.canvas;c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    try:
        ox,oy=c.image_origin
        e=input_event(ox+543*.4,oy+1010*.4)
        c.mousePressEvent(e);c.mouseReleaseEvent(e);c.mouseDoubleClickEvent(e);c.mouseReleaseEvent(e)
        assert not c.animator.interaction_active
        a=c.animator;a.begin_lift((543,790));a.move_lift((100,-100),40);a.advance(.2)
        a.release_lift();a.advance(.05)
        x,y=transform_point(root_matrix(a.pose),(325,610))
        e=input_event(ox+x*.4,oy+y*.4);c.mousePressEvent(e)
        a.advance(.08);current=a.pose.root_offset
        c.mouseMoveEvent(input_event(e.position().x(),e.position().y()-13))
        assert a.pose.root_offset==pytest.approx(current)
        assert a.lift.held
    finally:w.close()
