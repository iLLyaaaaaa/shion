"""Whole-head impact and procedural stars, independent of image assets."""
from dataclasses import replace
import random

import numpy as np
import pytest

from v3proto.animation import Animator, Pose, Settings
from v3proto.head_touch import HeadParameters
from v3proto.stars import (STAR_COUNT,STAR_MIN_COUNT,STAR_LIFETIME,MAX_STAR_BURSTS,STAR_GRAVITY,
                          StarBurst,make_star_burst,star_particles,paint_stars)


def quiet(**kwargs):
    return Settings(breath=False,blink=False,sway=False,**kwargs)


def test_impact_translates_whole_head_without_squashing_body_or_moving_arms():
    a=Animator(quiet())
    a.knock_head()
    assert a.advance(0).reaction_face=='teary'
    ys=[]
    for _ in range(60):
        p=a.advance(1/120)
        ys.append(p.head_y)
        assert p.body_scale==1 and p.arm_degrees==0
    assert 23<max(ys)<32
    assert abs(ys[-1])<.01
    assert max(abs(v) for v in np.diff(ys))<7


def test_stars_start_after_downstroke_then_expire_and_soothing_cancels_them():
    a=Animator(quiet());a.knock_head()
    assert a.advance(.06).star_age is None
    assert a.advance(.10).star_age==pytest.approx(.09)
    assert a.pose.head_y>5
    a.stroke_head(12)
    assert a.advance(0).star_age is None and a.pose.reaction_face=='happy'
    a.knock_head();a.advance(STAR_LIFETIME+.08)
    assert a.pose.star_age is None


def test_star_sampling_is_bounded_deterministic_and_has_no_queue():
    assert not star_particles(None) and not star_particles(-1) and not star_particles(STAR_LIFETIME)
    stars=star_particles(.22)
    assert stars==star_particles(.22) and STAR_MIN_COUNT<=len(stars)<=STAR_COUNT
    for t in np.linspace(0,STAR_LIFETIME,100):
        values=star_particles(float(t))
        assert len(values)<=STAR_COUNT
        for s in values:
            assert 0<=s.opacity<=1 and s.radius>0
            assert abs(s.x)<500 and -150<s.y<600


def test_launches_vary_per_click_but_a_snapshot_seed_is_reproducible():
    origin=(340.,270.)
    assert make_star_burst(origin,random.Random(17))==make_star_burst(origin,random.Random(17))
    rng=random.Random(23)
    bursts=[make_star_burst(origin,rng) for _ in range(24)]
    assert len(set(len(b.launches) for b in bursts))>=3
    assert len(set(bursts))==len(bursts)
    for b in bursts:
        assert b.origin==origin and STAR_MIN_COUNT<=len(b.launches)<=STAR_COUNT
        values=star_particles(.35,b)
        assert max(s.x for s in values)-min(s.x for s in values)>140


def test_stars_start_at_the_click_rise_then_fall_under_gravity_and_disappear():
    burst=make_star_burst((500,200),random.Random(2))
    for launch in burst.launches:
        single=StarBurst(burst.origin,(launch,))
        start=star_particles(launch.birth,single)[0]
        assert start.x==start.y==0
        apex=-launch.vy/STAR_GRAVITY
        t_up=apex*.5;t_down=min(launch.life-.04,apex+.2)
        before=star_particles(launch.birth+t_up,single)[0]
        after=star_particles(launch.birth+t_down,single)[0]
        earlier=star_particles(launch.birth+t_down-.01,single)[0]
        assert before.y<0 and after.y>earlier.y
        late=star_particles(launch.birth+launch.life-.02,single)[0]
        assert late.opacity<.02
        samples=[star_particles(launch.birth+.3+dt,single)[0].y for dt in (-.01,0,.01)]
        assert samples[2]-2*samples[1]+samples[0]==pytest.approx(STAR_GRAVITY*.01**2)
    assert not star_particles(STAR_LIFETIME,burst)


def test_click_bursts_keep_falling_independently_and_remain_bounded():
    a=Animator(quiet(),star_seed=5)
    a.knock_head(point=(350,260));a.advance(.15)
    first=a.pose.star_effects[0][1]
    a.knock_head(point=(630,260));a.advance(.10)
    assert len(a.pose.star_effects)==2 and a.pose.star_effects[0][1] is first
    assert a.pose.star_effects[1][1].origin==(630,260)
    for _ in range(20):a.knock_head();a.advance(.02)
    assert len(a._star_bursts)<=MAX_STAR_BURSTS
    a.advance(3)
    assert not a._star_bursts and not a.pose.star_effects


def test_star_randomness_does_not_change_the_blink_or_hair_random_stream():
    a=Animator(Settings(),star_seed=1);b=Animator(Settings(),star_seed=2)
    for _ in range(3):
        a.knock_head();b.knock_head()
        assert a.rng.getstate()==b.rng.getstate()
        assert a.advance(.12).angles==b.advance(.12).angles
    assert a._star_bursts!=b._star_bursts


def test_head_drop_is_continuous_when_pinch_takes_over_and_soothing_follows():
    a=Animator(quiet(expression='neutral'));a.knock_head();before=a.advance(.09)
    assert before.head_y>20
    a.press((325,610));after=a.advance(0)
    assert after.head_y==pytest.approx(before.head_y)
    assert after.reaction_face=='surprised' and after.reaction_base=='neutral'
    assert after.star_age is None
    a.advance(.03);a.release();before=a.advance(0)
    a.stroke_head(12);after=a.advance(0)
    assert after.head_y==pytest.approx(before.head_y)
    assert after.reaction_face=='happy'


def test_no_stars_or_displacement_survive_disable_reset_or_fade():
    for mode in ('disabled','faded'):
        s=quiet();a=Animator(s);a.knock_head();a.advance(.15)
        if mode=='disabled':s.knock=False;a.advance(0)
        else:a.advance(2)
        assert a.pose.is_rest and a.pose.star_age is None


@pytest.fixture(scope='module')
def rig():
    from v3proto.render import Rig
    return Rig()


def test_all_head_parts_share_translation_while_body_matrices_are_identical(rig):
    from v3proto.render import Renderer,BODY,LEGS
    from v3proto.motion import transform_point
    r=Renderer(rig,.4)
    a=Animator(quiet());a.knock_head();p=a.advance(.09)
    base=r.matrices(Pose());actual=r.matrices(p)
    for n in BODY|LEGS:assert np.array_equal(base[n],actual[n])
    for n in r.head_surface.names:
        point=(rig.parts[n]['x'],rig.parts[n]['y'])
        delta=transform_point(actual[n],point)-transform_point(base[n],point)
        assert delta==pytest.approx([0,p.head_y],abs=1e-8)
    source=np.array([500.,150.])
    assert r.hit_test(source+[0,p.head_y],quiet(),p,crown=True)[0]=='crown'


@pytest.mark.parametrize('scale',[.25,.4,.6])
def test_star_overlay_is_gold_fixed_to_click_and_does_not_mutate_cached_frame(rig,scale):
    from v3proto.render import Renderer,premultiplied
    r=Renderer(rig,scale);s=quiet(pinch=False)
    cached=r.render(s,Pose());original=premultiplied(cached)
    burst=make_star_burst((500,230),random.Random(10))
    p=Pose(star_effects=((.3,burst),))
    effect=paint_stars(cached,rig,scale,p)
    assert np.array_equal(original,premultiplied(cached))
    assert not np.array_equal(original,premultiplied(effect))
    # Pure-effect layers make gold color and attachment independent of the face below.
    from PySide6.QtGui import QImage
    empty=QImage(cached.size(),QImage.Format.Format_RGBA8888_Premultiplied);empty.fill(0)
    first=premultiplied(paint_stars(empty,rig,scale,p))
    independent=premultiplied(paint_stars(empty,rig,scale,replace(p,head_y=20)))
    assert np.array_equal(first,independent)
    moved_burst=replace(burst,origin=(520,260))
    moved=premultiplied(paint_stars(empty,rig,scale,replace(p,star_effects=((.3,moved_burst),))))
    y,x=np.where(first[...,3]>100)
    yy,xx=np.where(moved[...,3]>100)
    assert len(x)>30 and yy.mean()-y.mean()==pytest.approx(30*scale,abs=.3)
    assert xx.mean()-x.mean()==pytest.approx(20*scale,abs=.3)
    solid=first[first[...,3]>240]
    assert (solid[:,0]>200).all() and (solid[:,1]>150).all()
    assert (solid[:,2]<185).all()
    assert (solid[:,0]>=solid[:,1]).all() and (solid[:,1]>solid[:,2]).all()


def test_static_and_ordinary_render_paths_both_show_stars_and_restore(rig):
    from v3proto.render import Renderer,premultiplied
    for settings in (quiet(pinch=False),Settings()):
        r=Renderer(rig,.4);a=Animator(settings);a.knock_head();p=a.advance(.2)
        decorated=premultiplied(r.render(settings,p))
        plain=premultiplied(r.render(settings,replace(p,star_effects=())))
        assert (decorated!=plain).any()
        assert p.reaction_face=='teary'
        a.advance(3)
        assert a.pose.star_age is None
        if not settings.breath:assert a.pose.is_rest


def test_stars_outlive_a_short_face_reaction_without_changing_the_rest_artwork(rig):
    from v3proto.render import Renderer,premultiplied
    settings=quiet(head_touch=replace(HeadParameters(),knock_hold=.1,fade=.1))
    a=Animator(settings,star_seed=2);a.knock_head();p=a.advance(.35)
    assert p.rig_is_rest and not p.is_rest
    r=Renderer(rig,.4)
    assert np.array_equal(premultiplied(r._render_rig(settings,p)),premultiplied(r.render(settings,Pose())))
    settings.knock=False;a.advance(0)
    assert not a.pose.star_effects and a.pose.is_rest


@pytest.mark.parametrize('scale',[.25,.4,.6])
def test_real_canvas_click_passes_the_correct_rig_world_location(rig,scale):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from v3proto.window import Preview
    from tests.test_v3_head_touch import input_event
    app=QApplication.instance() or QApplication([])
    w=Preview(rig,quiet(),scale=scale)
    try:
        w.canvas.timer.stop();w.stats_timer.stop()
        for point in ((500,150),(540,150)):
            event=input_event(12+point[0]*scale,12+point[1]*scale)
            w.canvas.mousePressEvent(event);w.canvas.mouseReleaseEvent(event)
            assert w.canvas.animator._star_bursts[-1][1].origin==pytest.approx(point)
    finally:w.close();app.processEvents()
