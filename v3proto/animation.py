"""Stateful clock/input adapter around the pure motion functions."""
from dataclasses import dataclass, field
import math
import random

import numpy as np

from .reaction import ReactionParameters, ReactionState, press_reaction, release_reaction, step_reaction
from .motion import Spring, blink_scale, breathing, limit_vector, release_step, spring_step, limit_cheek_drag


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
    sway_degrees: float = 2.0
    pinch_maximum: float = 120.0
    pinch_radius: float = 110.0
    underlays_only: bool = False
    reaction: ReactionParameters = field(default_factory=ReactionParameters)


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

    @property
    def is_rest(self):
        return (self.body_scale == 1 and self.head_y == 0 and self.eye_scale == 1
                and not any(self.angles.values()) and not any(self.pinch_delta)
                and self.reaction_face is None and self.arm_degrees == 0 and self.head_roll == 0)


class Animator:
    def __init__(self, settings: Settings, seed: int = 7, now: float = 0.):
        self.settings = settings
        self.rng = random.Random(seed)
        self.time = 0.0
        self.clock = now
        self.reaction = ReactionState()
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
        self.blink_start = self.time + self.rng.uniform(3, 6)
        self.double_pending = False

    def press(self, point, now=None):
        if self.settings.pinch:
            if now is not None:self.clock = max(self.clock, now)
            self.reaction = press_reaction(self.reaction, self.clock, self.settings.expression,
                                           self.settings.reaction)
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
            self._last_expression = self.settings.expression
        if not self.settings.pinch:
            self.cancel_pinch()
        # Bounded substeps, also used by deterministic snapshots.
        remaining = dt
        while remaining > 1e-9:
            step = min(remaining, 1 / 120)
            remaining -= step
            self.time += step
            if self.settings.sway:
                drive=0.
                if self.settings.breath:
                    head=breathing(self.time,self.settings.breath_amount)[1]
                    previous=breathing(self.time-step,self.settings.breath_amount)[1]
                    drive=-(head-previous)/step*.10
                for i, n in enumerate(SWAY_PARTS):
                    ph = self.phases[n]
                    noise = 0.20 * math.sin(self.time * 1.7 + ph) + 0.12 * math.sin(self.time * 2.9 + ph)
                    gain=AHOGE_GAIN if n=='ahoge' else 1
                    target = self.settings.sway_degrees * gain * (drive + noise)
                    frequency,damping=(1.25,.38) if n=='ahoge' else (1.5+i*.12,.45)
                    s = spring_step(self.springs[n], step, target, frequency, damping)
                    cap = self.settings.sway_degrees*gain
                    pos = max(-cap,min(cap,s.position))
                    self.springs[n] = Spring(pos, s.velocity if pos == s.position else 0)
            if not self.dragging:
                self.delta, self.velocity = release_step(self.delta, self.velocity, step / (self.reaction.params.rebound_time if self.reaction.active else 1.),
                                                         self.settings.pinch_maximum)
            previous_stage = self.reaction.stage
            clock = end_clock - (end_clock - start_clock) * remaining / max(dt, 1e-12)
            self.reaction = step_reaction(self.reaction, clock, step,
                max(0., -self.delta[0]) / self.settings.pinch_maximum,
                not np.any(self.delta) and not np.any(self.velocity), self.velocity[0])
            if previous_stage != self.reaction.stage:self.reset_blink()
        self.clock = end_clock
        s = self.settings
        if not s.pinch:
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
                self.blink_start += self.rng.uniform(3, 6)
                self.double_pending = False
        scale, head_y = breathing(self.time, s.breath_amount) if s.breath else (1., 0.)
        r = self.reaction
        if r.active:
            scale -= r.body.position
            head_y += r.body.position * (1063.4 - 664.)
        self.pose = Pose(scale, head_y, blink_scale(self.time - self.blink_start, s.blink_amount),
                         {n: v.position for n, v in self.springs.items()}, tuple(self.center), tuple(self.delta),
                         r.face, r.base, r.fade, r.arm.position, r.head.position)
        return self.pose
