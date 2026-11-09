"""Only the protruding cheek can lift; its deformation lasts until release."""
import pytest
from tests.test_v3_lift import rig,quiet
from tests.test_v3_head_touch import input_event
from v3proto.animation import Animator


@pytest.mark.parametrize('pinch',[True,False])
def test_cheek_shape_is_frozen_until_release_even_with_pinch_disabled(pinch):
    a=Animator(quiet(pinch=pinch));a.press((325,610));a.drag((310,580));a.advance(0)
    a.begin_lift((325,586),cheek=True);a.advance(0)
    shape=a.pose.pinch_delta
    assert any(shape)
    for i in range(1,40):
        a.move_lift((i,-100),i*.4);a.advance(.05)
        assert a.pose.pinch_delta==shape
    a.release_lift();a.advance(.1)
    assert a.pose.pinch_delta!=shape
    a.advance(5);assert a.pose.is_rest


@pytest.mark.parametrize('point',[(543,880),(543,1010),(250,850),(543,1200),(530,580)])
def test_other_regions_never_lift_even_when_dragged_across_cheek(rig,point):
    from v3proto.window import Preview
    w=Preview(rig,quiet());c=w.canvas;c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    ox,oy=c.image_origin
    try:
        c.mousePressEvent(input_event(ox+point[0]*.4,oy+point[1]*.4))
        for x,y in [(0,-80),(100,-120),(-100,0)]:
            c.mouseMoveEvent(input_event(ox+point[0]*.4+x,oy+point[1]*.4+y))
            assert not c.animator.lift.active
        c.mouseReleaseEvent(input_event(ox+325*.4,oy+580*.4))
        assert not c.animator.lift.active
    finally:w.close()


@pytest.mark.parametrize('scale',[.25,.4,.6])
def test_horizontal_pinch_then_upward_lift_and_frozen_drag(rig,scale):
    from v3proto.window import Preview
    w=Preview(rig,quiet(),scale);c=w.canvas;c.timer.stop();w.stats_timer.stop();c.grabMouse=lambda:None
    ox,oy=c.image_origin;x,y=ox+325*scale,oy+610*scale
    try:
        c.mousePressEvent(input_event(x,y));c.mouseMoveEvent(input_event(x-20,y))
        assert c.animator.dragging and not c.animator.lift.active
        c.mouseMoveEvent(input_event(x,y-12));assert not c.animator.lift.active
        c.mouseMoveEvent(input_event(x,y-12.1));assert c.animator.lift.held
        shape=tuple(c.animator.delta)
        c.animator.advance(.5)
        c.mouseMoveEvent(input_event(x+20,y-30))
        assert tuple(c.animator.delta)==shape
        assert c.animator.pose.root_offset==pytest.approx((20/scale,-17.9/scale))
        c.mouseReleaseEvent(input_event(x+20,y-30))
        c.animator.advance(.1);assert tuple(c.animator.delta)!=shape
        c.animator.advance(5);assert c.animator.pose.is_rest
    finally:w.close()
