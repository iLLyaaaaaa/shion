"""Stateful clock/input adapter around the pure motion functions."""
from dataclasses import dataclass, field, replace
import math
import random

import numpy as np

from .reaction import ReactionParameters, ReactionState, press_reaction, release_reaction, step_reaction
from .motion import Spring, blink_scale, breathing, limit_vector, release_step, spring_step, limit_cheek_drag
from .head_touch import HeadParameters, HeadState, knock_head, stroke_head, release_head, step_head
from .stars import STAR_LIFETIME,MAX_STAR_BURSTS,make_star_burst
from .lift import LiftState, begin_lift, move_lift, release_lift, step_lift
from .tickle import TickleState, stroke_tickle, release_tickle, step_tickle, TORSO_PIVOT, NECK_PIVOT
from .motion import pivot_matrix, transform_point


SWAY_PARTS = ("bangs", "ahoge", "flower", "side_hair_l", "side_hair_r", "ribbon")
AHOGE_GAIN = 4.0


@dataclass
class Settings:
    expression: str = "smug"
    breath: bool = True
    blink: bool = True
    sway: bool = True
    pinch: bool = True
    breath_amount: float = 1.0
    blink_amount: float = 1.0
    breath_rate: float = 1.0  # 呼吸快慢倍数（<1 变慢）；1 时与原来逐位相同
    blink_gap: float = 1.0    # 眨眼间隔倍数（>1 变稀）；1 时与原来逐位相同
    sway_degrees: float = 2.0
    pinch_maximum: float = 120.0
    pinch_radius: float = 110.0
    underlays_only: bool = False
    reaction: ReactionParameters = field(default_factory=ReactionParameters)
    knock: bool = True
    pat: bool = True
    head_touch: HeadParameters = field(default_factory=HeadParameters)
    lift: bool = True
    tickle: bool = True
    arms: str = "default"  # "hold"：抱电脑整块（arms_hold）代替两条手臂


@dataclass
class Pose:
    body_scale: float = 1.0
    head_y: float = 0.0
    eye_scale: float = 1.0
    angles: dict = field(default_factory=dict)
    pinch_center: tuple = (535.0, 550.0)
    pinch_delta: tuple = (0.0, 0.0)

    reaction_face: str | None = None
    reaction_base: str | None = None
    reaction_fade: float = 0.
    arm_degrees: float = 0.
    head_roll: float = 0.
    star_effects: tuple = ()  # (age, immutable click burst); world coordinates, not head-local.
    root_offset: tuple = (0., 0.)
    root_roll: float = 0.
    root_pivot: tuple = (543., 790.)
    leg_degrees: float = 0.
    body_roll: float = 0.
    head_x: float = 0.

    @property
    def is_rest(self):
        return (self.rig_is_rest and not self.star_effects
                and not any(self.root_offset) and self.root_roll == 0)

    @property
    def star_age(self):
        return self.star_effects[-1][0] if self.star_effects else None

    @property
    def rig_is_rest(self):
        return (self.body_scale == 1 and self.head_y == 0 and self.eye_scale == 1
                and not any(self.angles.values()) and not any(self.pinch_delta)
                and self.reaction_face is None and self.arm_degrees == 0 and self.head_roll == 0
                and self.leg_degrees == 0 and self.body_roll == 0 and self.head_x == 0)


class Animator:
    def __init__(self, settings: Settings, seed: int = 7, now: float = 0., *, star_seed=None):
        self.settings = settings
        self.rng = random.Random(seed)
        self.star_rng = random.Random(star_seed)
        self._star_bursts = ()
        self.time = 0.0
        self.breath_time = 0.0  # 按 breath_rate 推进的呼吸相位时钟
        self.clock = now
        self.reaction = ReactionState()
        self.head_touch = HeadState()
        self.lift = LiftState()
        self.tickle = TickleState()
        self._lift_cheek = False
        self._rebound_time = 1.
        self.blink_start = self.rng.uniform(3, 6)
        self.double_pending = False
        self.springs = {n: Spring() for n in SWAY_PARTS}
        self.phases = {n: self.rng.uniform(0, math.tau) for n in SWAY_PARTS}
        self.dragging = False
        self.center = np.array([535., 550.])
        self.delta = np.zeros(2)
        self.velocity = np.zeros(2)
        self._drag_origin=self.center.copy()
        self._drag_base=self.delta.copy()
        self.pose = Pose()
        self._last_expression = settings.expression

    def reset_blink(self):
        self.blink_start = self.time + self.rng.uniform(3, 6) * self.settings.blink_gap
        self.double_pending = False

    def press(self, point, now=None):
        if self.settings.pinch and not self.lift.held:
            if now is not None:self.clock = max(self.clock, now)
            self._yield_tickle()
            self._yield_lift()
            if self.head_touch.active:
                h = step_head(self.head_touch, self.clock, 0.)
                weight = 1-h.fade
                scaled = lambda v: Spring(v.position*weight, v.velocity*weight)
                self.reaction = replace(self.reaction, base=h.base, body=scaled(h.body),
                                        arm=scaled(h.arm), head=scaled(h.head), drop=scaled(h.drop))
            self.cancel_head()
            self.reaction = press_reaction(self.reaction, self.clock, self.settings.expression,
                                           self.settings.reaction)
            self._rebound_time = self.reaction.params.rebound_time
            self.reset_blink()
            if not np.any(self.delta):self.center=np.array(point,dtype=float)
            self._drag_origin=np.array(point,dtype=float)
            self._drag_base=self.delta.copy()
            self.velocity[:]=0
            self.dragging = True

    def drag(self, point):
        if self.dragging:
            movement=limit_cheek_drag(np.array(point)-self._drag_origin,self.settings.pinch_maximum)
            self.delta=limit_vector(self._drag_base+movement,self.settings.pinch_maximum)

    def release(self, now=None):
        if now is not None:self.clock = max(self.clock, now)
        if self.dragging:
            self.reaction = release_reaction(self.reaction, self.clock)
            self.reset_blink()
            self.velocity[:] = 0
        self.dragging = False

    def impulse(self, direction=1.0):
        if self.settings.sway:
            for i, n in enumerate(SWAY_PARTS):
                s = self.springs[n]
                gain=AHOGE_GAIN if n=='ahoge' else 1
                self.springs[n] = Spring(s.position, s.velocity + direction * (12 + i)*gain)

    @property
    def interaction_active(self):
        return self.reaction.active or self.head_touch.active or self.lift.active or self.tickle.active

    @property
    def original_expression(self):
        return self.reaction.base or self.head_touch.base or self.lift.base or self.tickle.base or self.settings.expression

    def begin_lift(self, pivot, now=None, *, cheek=False):
        if not self.settings.lift or self.settings.underlays_only or (self.dragging and not cheek):
            return
        if now is not None:self.clock = max(self.clock, now)
        self._yield_tickle()
        self._lift_cheek = cheek
        if cheek:
            self.dragging = False
            if not np.any(self.delta):self.delta = np.array([0.,-24.])
        base = self.original_expression
        r = self.head_touch if self.head_touch.active else self.reaction
        if self.lift.active and self.lift.owns_face:r = self.lift
        weight = 1-r.fade if r.active else 0.
        seed = replace(self.pose, body_scale=1-r.body.position*weight,
                       head_y=(r.body.position*399.4+r.drop.position)*weight,
                       head_roll=self.pose.head_roll-self.pose.body_roll)
        self.lift = begin_lift(self.lift, self.clock, base, pivot, seed)
        self._rebound_time = self.reaction.params.rebound_time if self.reaction.active else self._rebound_time
        self.reaction = ReactionState(history=self.reaction.history, count=self.reaction.count)
        self.cancel_head()
        self.reset_blink()

    def move_lift(self, offset, logical_x, now=None, clamp=True):
        if now is not None:self.clock = max(self.clock, now)
        self.lift = move_lift(self.lift, offset, logical_x, self.clock, clamp)

    def release_lift(self, now=None):
        if now is not None:self.clock = max(self.clock, now)
        self.lift = release_lift(self.lift, self.clock)

    def _yield_lift(self):
        """New touches own the face while an already released root returns home."""
        if self.lift.active and self.lift.owns_face:
            r = step_lift(self.lift, self.clock)
            weight = 1-r.fade
            scaled = lambda v: Spring(v.position*weight, v.velocity*weight)
            self.reaction = replace(self.reaction, base=r.base, body=scaled(r.body),
                                    arm=scaled(r.arm), head=scaled(r.head), drop=scaled(r.drop))
            self.lift = replace(r, owns_face=False)

    def cancel_head(self):
        self.head_touch = HeadState()
        self._star_bursts = ()

    def _head_seed(self, now):
        if now is not None:
            self.clock = max(self.clock, now)
        self._yield_tickle()
        self._yield_lift()
        h = step_head(self.head_touch, self.clock, 0.)
        if self.reaction.active:
            r = self.reaction
            weight = 1-r.fade
            scaled = lambda v: Spring(v.position*weight, v.velocity*weight)
            h = replace(h, base=r.base, body=scaled(r.body), arm=scaled(r.arm), head=scaled(r.head),
                        drop=scaled(r.drop))
            # Geometry/velocity keep returning independently; its old face never resumes.
            self._rebound_time = r.params.rebound_time
            self.reaction = ReactionState(history=r.history, count=r.count)
        return h

    def knock_head(self, direction=1., now=None, *, point=(500.,150.)):
        if self.dragging or self.lift.held or not self.settings.knock or self.settings.underlays_only:
            return
        h = self._head_seed(now)
        self.head_touch = knock_head(h, self.clock, self.settings.expression, self.settings.head_touch)
        born = self.clock+self.head_touch.params.nod_time*.25
        active = tuple((t,b) for t,b in self._star_bursts if self.clock-t<STAR_LIFETIME)
        self._star_bursts = (active+((born,make_star_burst(point,self.star_rng)),))[-MAX_STAR_BURSTS:]
        self.impulse(direction*.4)
        self.reset_blink()

    def stroke_head(self, dx, now=None):
        if self.dragging or self.lift.held or not self.settings.pat or self.settings.underlays_only or not dx:
            return
        h = self._head_seed(now)
        self._star_bursts = ()
        self.head_touch = stroke_head(h, self.clock, dx, self.settings.expression, self.settings.head_touch)
        if h.kind != "pat" or h.face != "happy":
            self.reset_blink()

    def release_head(self, now=None):
        if now is not None:self.clock = max(self.clock, now)
        self.head_touch = release_head(self.head_touch, self.clock)

    def tickle_belly(self, now=None):
        if self.dragging or self.lift.held or not self.settings.tickle or self.settings.underlays_only:
            return
        if now is not None:self.clock = max(self.clock, now)
        t = step_tickle(self.tickle,self.clock)
        if not t.active or not t.owns_face:
            h = self._head_seed(self.clock)
            weight = 1-h.fade
            scaled = lambda v: Spring(v.position*weight,v.velocity*weight)
            t = replace(t,base=h.base or self.settings.expression,body=scaled(h.body),
                        arm=scaled(h.arm),head=scaled(h.head),drop=scaled(h.drop),
                        started_at=self.clock,updated_at=self.clock)
            self.reaction = ReactionState(history=self.reaction.history,count=self.reaction.count)
            self.cancel_head()
            self.reset_blink()
        self.tickle = stroke_tickle(t,self.clock,self.settings.expression)

    def release_tickle(self, now=None):
        if now is not None:self.clock = max(self.clock,now)
        self.tickle = release_tickle(self.tickle,self.clock)

    def _yield_tickle(self):
        if not self.tickle.active or not self.tickle.owns_face:
            return
        t = step_tickle(self.tickle,self.clock)
        if t.active:
            weight = 1-t.fade
            scaled = lambda v: Spring(v.position*weight,v.velocity*weight)
            self.reaction = replace(self.reaction,base=t.base,body=scaled(t.body),arm=scaled(t.arm),
                                    head=scaled(t.head),drop=scaled(t.drop))
            t = replace(release_tickle(t,self.clock),owns_face=False)
        self.tickle = t

    def cancel_pinch(self):
        self.dragging = False
        self.delta[:] = self.velocity[:] = 0
        self.reaction = ReactionState()

    def advance(self, dt: float, now=None) -> Pose:
        if dt < 0:
            raise ValueError("time must advance")
        end_clock = self.clock + dt if now is None else max(self.clock, now)
        start_clock = self.clock
        if self.settings.expression != self._last_expression:
            self.reset_blink()
            self.cancel_pinch()
            self.cancel_head()
            self.lift = LiftState()
            self.tickle = TickleState()
            self._last_expression = self.settings.expression
        if self.settings.underlays_only:
            self.lift = LiftState()
            self.tickle = TickleState()
        elif not self.settings.lift:
            self.release_lift(now=end_clock)
        if not self.settings.tickle:
            self.release_tickle(now=end_clock)
        if not self.settings.pinch and not (self._lift_cheek and np.any(self.delta)):
            self.cancel_pinch()
        if ((self.head_touch.kind == 'knock' and not self.settings.knock)
                or (self.head_touch.kind == 'pat' and not self.settings.pat)
                or self.settings.underlays_only):
            self.cancel_head()
        if not self.settings.knock:
            self.head_touch = replace(self.head_touch, count=0, last_knock=None)
            self._star_bursts = ()
        # Bounded substeps, also used by deterministic snapshots.
        remaining = dt
        while remaining > 1e-9:
            step = min(remaining, 1 / 120)
            remaining -= step
            self.time += step
            breath_step = step * self.settings.breath_rate
            self.breath_time += breath_step
            if self.settings.sway:
                drive=0.
                if self.settings.breath:
                    head=breathing(self.breath_time,self.settings.breath_amount)[1]
                    previous=breathing(self.breath_time-breath_step,self.settings.breath_amount)[1]
                    drive=-(head-previous)/step*.10
                for i, n in enumerate(SWAY_PARTS):
                    ph = self.phases[n]
                    noise = 0.20 * math.sin(self.time * 1.7 + ph) + 0.12 * math.sin(self.time * 2.9 + ph)
                    gain=AHOGE_GAIN if n=='ahoge' else 1
                    target = self.settings.sway_degrees * gain * (drive + noise)
                    h = self.head_touch
                    if h.kind == 'pat' and h.active and end_clock-h.last_move < h.params.follow_time:
                        target += self.settings.sway_degrees * gain * h.direction * .18
                    if self.lift.active:
                        speed = self.lift.velocity*math.exp(-max(0.,end_clock-self.lift.moved_at)/.1)
                        target += max(-1.,min(1.,speed/800))*self.settings.sway_degrees*gain*.4
                    frequency,damping=(1.25,.38) if n=='ahoge' else (1.5+i*.12,.45)
                    s = spring_step(self.springs[n], step, target, frequency, damping)
                    cap = self.settings.sway_degrees*gain
                    pos = max(-cap,min(cap,s.position))
                    self.springs[n] = Spring(pos, s.velocity if pos == s.position else 0)
            if not self.dragging and not (self.lift.held and self._lift_cheek):
                self.delta, self.velocity = release_step(self.delta, self.velocity, step / self._rebound_time,
                                                         self.settings.pinch_maximum)
            previous_stage = self.reaction.stage
            clock = end_clock - (end_clock - start_clock) * remaining / max(dt, 1e-12)
            self.reaction = step_reaction(self.reaction, clock, step,
                max(0., -self.delta[0]) / self.settings.pinch_maximum,
                not np.any(self.delta) and not np.any(self.velocity), self.velocity[0])
            if previous_stage != self.reaction.stage:self.reset_blink()
            previous_head_stage = self.head_touch.stage
            self.head_touch = step_head(self.head_touch, clock, step)
            if previous_head_stage != self.head_touch.stage:self.reset_blink()
            self.tickle = step_tickle(self.tickle,clock)
        self.clock = end_clock
        self.lift = step_lift(self.lift, self.clock)
        self.tickle = step_tickle(self.tickle,self.clock)
        self.head_touch = step_head(self.head_touch, self.clock, 0.)
        s = self.settings
        if not s.pinch and not (self._lift_cheek and np.any(self.delta)):
            self.dragging = False
            self.delta[:] = self.velocity[:] = 0
        self.delta = limit_vector(self.delta, s.pinch_maximum)
        if not s.sway:
            self.springs = {n: Spring() for n in SWAY_PARTS}
        if not s.blink or s.blink_amount == 0:
            self.reset_blink()
        while self.time >= self.blink_start + 0.150:
            if not self.double_pending and self.rng.random() < 0.15:
                self.blink_start += 0.24
                self.double_pending = True
            else:
                self.blink_start += self.rng.uniform(3, 6) * s.blink_gap
                self.double_pending = False
        scale, head_y = breathing(self.breath_time, s.breath_amount) if s.breath else (1., 0.)
        r = self.reaction
        if self.head_touch.active:
            r = self.head_touch
        if self.lift.active and self.lift.owns_face:
            r = self.lift
        if self.tickle.active and self.tickle.owns_face:
            r = self.tickle
        if r.active:
            weight = 1-r.fade if isinstance(r, (HeadState,LiftState,TickleState)) else 1.
            scale -= r.body.position * weight
            head_y += r.body.position * weight * (1063.4 - 664.)
            head_y += r.drop.position * weight
        else:
            weight = 1.
        self.pose = Pose(scale, head_y, blink_scale(self.time - self.blink_start, s.blink_amount),
                         {n: v.position for n, v in self.springs.items()}, tuple(self.center), tuple(self.delta),
                         r.face, r.base, r.fade, r.arm.position*weight, r.head.position*weight)
        self._star_bursts = tuple((t,b) for t,b in self._star_bursts if self.clock-t<STAR_LIFETIME)
        self.pose.star_effects = tuple((self.clock-t,b) for t,b in self._star_bursts if self.clock>=t)
        self.pose.root_offset = self.lift.offset
        self.pose.root_roll = self.lift.roll.position
        self.pose.root_pivot = self.lift.pivot
        self.pose.leg_degrees = self.lift.leg.position*(1-self.lift.fade)
        self.pose.body_roll = self.tickle.torso.position*(1-self.tickle.fade)
        if self.pose.body_roll:
            # Rotate the complete head around the waist along with the torso.
            # Legs keep their existing hip anchors; breathing remains unchanged.
            neck = NECK_PIVOT
            x,y = transform_point(pivot_matrix(TORSO_PIVOT,self.pose.body_roll),
                                  (neck[0],neck[1]+self.pose.head_y))
            self.pose.head_x = x-neck[0]
            self.pose.head_y = y-neck[1]
            self.pose.head_roll += self.pose.body_roll
        return self.pose
