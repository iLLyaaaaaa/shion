"""Reuse only unchanged cheek material; facial overlays must not modify it."""
from dataclasses import replace
import numpy as np
from tests.test_v3_lift import rig,quiet
from v3proto.animation import Pose


def test_same_material_hits_cache_but_source_identity_invalidates(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4);h=r.head_surface;s=quiet()
    p=Pose(pinch_delta=(0,-24),reaction_face='teary')
    h.compose(s,p);original=h.cheek.last_deformation[0]
    first=h.cheek.apply(h,s,p,original=original)
    assert h.cheek.apply(h,s,p,original=original) is first
    second=h.cheek.apply(h,s,p,original=original.copy())
    assert second is not first and np.array_equal(second,first)
    assert not first.flags.writeable


def test_cached_composition_matches_uncached_across_all_changing_inputs(rig):
    from v3proto.render import Renderer
    r=Renderer(rig,.4);h=r.head_surface;s=quiet()
    cases=[(s,Pose(pinch_delta=(0,-24),reaction_face='teary')),
           (s,Pose(pinch_delta=(0,-24),reaction_face='happy',eye_scale=.2)),
           (s,Pose(pinch_delta=(-60,-12),reaction_face='angry')),
           (replace(s,pinch_radius=140),Pose(pinch_delta=(-60,-12),reaction_face='angry')),
           (replace(s,pinch_maximum=160),Pose(pinch_delta=(-60,-12),reaction_face='angry')),
           (replace(s,expression='neutral'),Pose(pinch_delta=(-60,-12))),
           (s,Pose(pinch_delta=(-1,0),reaction_face='teary',reaction_fade=.6))]
    for settings,p in cases:
        actual=h.compose(settings,p).copy()
        saved=h.cheek.last_deformation[2]
        material=saved.copy()
        h.compose(settings,replace(p,reaction_face='happy'))
        assert np.array_equal(material,saved)
        h.cheek.last_deformation=None
        expected=h.compose(settings,p)
        assert np.array_equal(actual,expected)
