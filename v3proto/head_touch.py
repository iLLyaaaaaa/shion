"""Rig head interactions, with injected monotonic time and no UI dependencies."""
from dataclasses import dataclass, field, replace
import math

from .motion import Spring, spring_step

CLICK_SLOP = 6.0  # Qt logical pixels, independent of rig/display scale.
PAT_THRESHOLD = 12.0
PAT_INPUT_EPSILON = 2.0


@dataclass(frozen=True)
class HeadParameters:
    head_drop: float = 28.0  # Reference pixels; the whole head translates together.
    knock_gap: float = 1.5
    knock_count: int = 3
    protest: float = 2.0
    tilt: float = 2.5
    return_time: float = .25
    after_hold: float = 1.5
    fade: float = .35
    knock_hold: float = .9
    nod_time: float = .28
    follow_time: float = .08

    def __post_init__(self):
        if not all(math.isfinite(v) and v >= 0 for v in vars(self).values()):
            raise ValueError("head parameters must be finite and nonnegative")
        if (int(self.knock_count) != self.knock_count or self.knock_count < 2
                or self.return_time <= self.follow_time or self.follow_time <= 0
                or self.nod_time <= 0 or self.tilt > 5 or self.head_drop > 60):
            raise ValueError("invalid head timing, count or amplitude")


@dataclass(frozen=True)
class HeadState:
    kind: str | None = None
    base: str | None = None
    stage: str = "idle"
    face: str | None = None
    at: float = 0.
    until: float = 0.
    last_move: float = 0.
    released_at: float | None = None
    direction: float = 0.
    tilt_origin: float = 0.
    count: int = 0
    last_knock: float | None = None
    fade: float = 0.
    params: HeadParameters = field(default_factory=HeadParameters)
    body: Spring = field(default_factory=Spring)
    arm: Spring = field(default_factory=Spring)
    head: Spring = field(default_factory=Spring)
    drop: Spring = field(default_factory=Spring)

    @property
    def active(self):
        return self.base is not None


def smooth(u):
    u = min(1., max(0., u))
    return u * u * (3 - 2 * u)


def pat_tilt(state, now):
    """Event-time trajectory: rendering more often cannot change the motion."""
    p = state.params
    elapsed = max(0., now - (state.released_at if state.released_at is not None else state.last_move))
    if elapsed >= p.return_time:
        return 0.
    if state.released_at is not None:
        return state.tilt_origin * (1 - smooth(elapsed / p.return_time))
    target = state.direction * p.tilt
    approach = 1 - math.exp(-min(elapsed, p.follow_time) / p.follow_time)
    angle = state.tilt_origin + (target - state.tilt_origin) * approach
    envelope = 1 - smooth((elapsed - p.follow_time) / (p.return_time - p.follow_time))
    return angle * envelope


def knock_head(state, now, expression, params):
    count = state.count + 1 if (state.last_knock is not None
                               and 0 <= now - state.last_knock <= params.knock_gap) else 1
    protesting = (state.kind == "knock" and state.stage == "protest" and now < state.until)
    repeated = protesting or count >= params.knock_count
    return replace(state, kind="knock", base=state.base or expression,
                   stage="protest" if repeated else "knock", face="teary",
                   at=now, until=now + (params.protest if repeated else params.knock_hold),
                   count=0 if repeated else count, last_knock=now, fade=0., params=params,
                   released_at=None, direction=0.)


def stroke_head(state, now, dx, expression, params):
    if not dx:
        return state
    p = state.params if state.kind == "pat" and state.active else params
    origin = pat_tilt(state, now) if state.kind == "pat" else state.head.position
    return replace(state, kind="pat", base=state.base or expression, stage="pat", face="happy",
                   at=now if state.kind != "pat" else state.at, last_move=now,
                   released_at=None, until=now+p.after_hold, direction=math.copysign(1., dx),
                   tilt_origin=origin, count=0, last_knock=None, fade=0., params=p,
                   head=Spring(origin))


def release_head(state, now):
    if state.kind != "pat" or not state.active or state.released_at is not None:
        return state
    return replace(state, released_at=now, tilt_origin=pat_tilt(state, now),
                   until=now+state.params.after_hold)


def step_head(state, now, dt):
    if dt < 0:
        raise ValueError("time must advance")
    if not state.active:
        return state
    p = state.params
    fade = smooth((now - state.until) / p.fade) if p.fade else float(now >= state.until)
    if fade >= 1:
        return HeadState(count=state.count, last_knock=state.last_knock)
    age = max(0., now-state.at)
    down = 0.
    if state.kind == "knock" and age < p.nod_time:
        phase = age/p.nod_time
        if phase < .25:
            down = p.head_drop * smooth(phase/.25)
        elif phase < .8:
            down = p.head_drop * (1-smooth((phase-.25)/.55))
        else:
            down = -.08*p.head_drop*math.sin(math.pi*(phase-.8)/.2)**2
    # Preserve incoming secondary motion while the head alone takes the impact.
    body = spring_step(state.body, dt, 0., frequency=10, damping=.7)
    arm = spring_step(state.arm, dt, 0., frequency=10, damping=.7)
    drop = spring_step(state.drop, dt, down, frequency=14, damping=.75)
    head = (Spring(pat_tilt(state, now)) if state.kind == "pat" else
            spring_step(state.head, dt, 0., frequency=5, damping=.7))
    stage = "fade" if now >= state.until else state.stage
    return replace(state, body=body, arm=arm, head=head, drop=drop, stage=stage, fade=fade)


class HeadGesture:
    """A press belongs to the crown until release, including outside the canvas."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.origin = None
        self.last_x = 0.
        self.moved = self.patting = False

    @property
    def active(self):
        return self.origin is not None

    def press(self, point):
        self.clear()
        self.origin = tuple(point)
        self.last_x = point[0]

    def move(self, point, enabled=True):
        if not self.active:
            return 0.
        x, y = point
        dx, dy = x-self.origin[0], y-self.origin[1]
        self.moved |= math.hypot(dx, dy) > CLICK_SLOP
        if not self.patting and enabled and abs(dx) >= PAT_THRESHOLD:
            self.patting = True
            self.last_x = x
            return dx
        if self.patting and enabled and abs(x-self.last_x) >= PAT_INPUT_EPSILON:
            delta, self.last_x = x-self.last_x, x
            return delta
        return 0.

    def release(self):
        click = self.active and not self.moved and not self.patting
        self.clear()
        return click
