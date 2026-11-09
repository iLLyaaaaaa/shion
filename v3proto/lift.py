"""Body grabbing and lift motion. Inputs use monotonic seconds, no UI clocks."""
from dataclasses import dataclass, field, replace
import math

from .motion import Spring, spring_step, pivot_matrix, translation


CLICK_SLOP = 6.0  # Qt logical pixels, independent of texture scale / DPR.
SHAKE_DISTANCE = 24.0
SHAKE_WINDOW = 2.0
SHAKE_COUNT = 3
RETURN_TIME = .90
AFTER_HOLD = .60
DIZZY_HOLD = 2.0
FADE_TIME = .35
MAX_ROLL = 8.0
SCENE_PADDING = (360, 280, 360, 100)  # Space for a foot grab tilted at either edge.
OFFSET_X = 240.0
OFFSET_Y = (-220.0, 40.0)


def root_matrix(pose):
    return translation(*pose.root_offset) @ pivot_matrix(pose.root_pivot, pose.root_roll)


def clamp_offset(point):
    return (max(-OFFSET_X, min(OFFSET_X, point[0])),
            max(OFFSET_Y[0], min(OFFSET_Y[1], point[1])))


@dataclass
class BodyGesture:
    origin: tuple | None = None
    point: tuple = (0., 0.)
    offset: tuple = (0., 0.)
    started: bool = False

    @property
    def active(self):
        return self.origin is not None

    def press(self, logical, point, offset):
        self.origin, self.point, self.offset = tuple(logical), tuple(point), tuple(offset)
        self.started = False

    def move(self, logical):
        if not self.active:
            return False
        if math.dist(self.origin, logical) > CLICK_SLOP:
            self.started = True
        return self.started

    def clear(self):
        self.origin = None
        self.started = False


@dataclass(frozen=True)
class LiftState:
    base: str | None = None
    owns_face: bool = True
    stage: str = 'idle'
    face: str | None = None
    fade: float = 0.
    pressed_at: float = 0.
    updated_at: float = 0.
    moved_at: float = 0.
    released_at: float | None = None
    offset: tuple = (0., 0.)
    release_offset: tuple = (0., 0.)
    pivot: tuple = (543., 790.)
    velocity: float = 0.
    roll: Spring = field(default_factory=Spring)
    release_roll: Spring = field(default_factory=Spring)
    body: Spring = field(default_factory=Spring)
    arm: Spring = field(default_factory=Spring)
    head: Spring = field(default_factory=Spring)
    drop: Spring = field(default_factory=Spring)
    leg: Spring = field(default_factory=Spring)
    direction: int = 0
    extreme: float = 0.
    shakes: tuple = ()
    dizzy: bool = False

    @property
    def active(self):
        return self.base is not None

    @property
    def held(self):
        return self.active and self.released_at is None


def begin_lift(state, now, expression, pivot, pose):
    # Retain the old pivot on regrab: changing it while tilted would move the art.
    return LiftState(base=expression, stage='held', face='surprised',
                     pressed_at=now, updated_at=now, moved_at=now,
                     offset=pose.root_offset, pivot=state.pivot if state.active else tuple(pivot),
                     roll=state.roll if state.active else Spring(),
                     body=Spring(1-pose.body_scale), arm=Spring(pose.arm_degrees),
                     head=Spring(pose.head_roll), drop=Spring(pose.head_y-(1-pose.body_scale)*399.4),
                     leg=Spring(pose.leg_degrees))


def move_lift(state, offset, logical_x, now):
    if not state.held:
        return state
    offset = clamp_offset(offset)
    dt = now-state.moved_at
    velocity = state.velocity
    if dt > 1e-6:
        speed = max(-2200., min(2200., (offset[0]-state.offset[0])/dt))
        velocity += (speed-velocity)*(1-math.exp(-dt/.06))
    direction, extreme, shakes = state.direction, state.extreme, state.shakes
    if not direction:
        if abs(logical_x) >= 1e-6:
            direction, extreme = (1 if logical_x > 0 else -1), logical_x
    elif (logical_x-extreme)*direction >= 0:
        extreme = logical_x
    elif abs(logical_x-extreme) >= SHAKE_DISTANCE:
        direction, extreme = -direction, logical_x
        shakes = tuple(t for t in shakes if now-SHAKE_WINDOW <= t <= now)+(now,)
    return replace(state, offset=offset, moved_at=now, velocity=velocity,
                   direction=direction, extreme=extreme, shakes=shakes,
                   dizzy=state.dizzy or len(shakes) >= SHAKE_COUNT)


def release_lift(state, now):
    if not state.held:
        return state
    state = step_lift(state, now)
    return replace(state, released_at=now, stage='return',
                   release_offset=state.offset, release_roll=state.roll, velocity=0.)


def step_lift(state, now):
    if not state.active:
        return state
    dt = max(0., now-state.updated_at)
    age = max(0., now-state.pressed_at)
    if state.held:
        # Stopping the pointer decays the drive; holding still is not shaking.
        speed = state.velocity*math.exp(-max(0., now-state.moved_at)/.10)
        target = max(-MAX_ROLL, min(MAX_ROLL, -speed*.006))
        roll = spring_step(state.roll, dt, target, 3., .7)
        if abs(roll.position) > MAX_ROLL:
            roll = Spring(math.copysign(MAX_ROLL,roll.position),0.)
        offset, stage, fade = state.offset, 'held', 0.
        arm_target = 5.+2.*math.sin(age*math.tau*2.5)
        leg_target = 3.*math.sin(age*math.tau*1.7)
        face = 'dizzy' if state.dizzy else ('surprised' if age < .20 else 'teary')
    else:
        elapsed = max(0., now-state.released_at)
        # Analytic elapsed-time sampling: a stalled UI does not stretch the return.
        offset = tuple(spring_step(Spring(x), elapsed, frequency=2.4, damping=.68).position
                       for x in state.release_offset) if elapsed < RETURN_TIME else (0., 0.)
        roll = (spring_step(state.release_roll, elapsed, frequency=2.4, damping=.68)
                if elapsed < RETURN_TIME else Spring())
        hold = DIZZY_HOLD if state.dizzy else AFTER_HOLD
        if not state.owns_face and elapsed >= RETURN_TIME:
            return LiftState()
        if elapsed >= RETURN_TIME+hold+FADE_TIME:
            return LiftState()
        stage = 'return' if elapsed < RETURN_TIME else ('hold' if elapsed < RETURN_TIME+hold else 'fade')
        u = max(0., min(1., (elapsed-RETURN_TIME-hold)/FADE_TIME))
        fade = u*u*(3-2*u)
        arm_target = leg_target = 0.
        face = 'dizzy' if state.dizzy else 'teary'
    return replace(state, updated_at=now, offset=offset, roll=roll, stage=stage, face=face, fade=fade,
                   body=spring_step(state.body, dt, 0., 3., .7),
                   arm=spring_step(state.arm, dt, arm_target, 3., .7),
                   head=spring_step(state.head, dt, 0., 3., .7),
                   drop=spring_step(state.drop, dt, 0., 3., .7),
                   leg=spring_step(state.leg, dt, leg_target, 3., .7))
