"""Belly rubbing and happy squirming, independent of Qt and persistent state."""
from dataclasses import dataclass, field, replace
import math

from .motion import Spring, spring_step


BELLY_CENTER = (543., 880.)
BELLY_RADII = (108., 90.)
RUB_REACH = 120.0  # Qt logical pixels; never reference pixels or device pixels.
REVERSE_DISTANCE = 8.0
REVERSE_WINDOW = 1.5
REVERSE_COUNT = 2
MOVE_EPSILON = 2.0
STOP_DELAY = .22
SETTLE_TIME = .35
AFTER_HOLD = .40
FADE_TIME = .35
TORSO_PIVOT = (544.1,1063.4)
NECK_PIVOT = (546.5,664.)


def in_belly(point):
    return sum(((v-c)/r)**2 for v,c,r in zip(point,BELLY_CENTER,BELLY_RADII)) <= 1.


@dataclass
class BellyGesture:
    origin: tuple | None = None
    last_x: float = 0.
    extreme: float = 0.
    direction: int = 0
    reversals: tuple = ()
    tickling: bool = False

    @property
    def active(self):
        return self.origin is not None

    def press(self, logical):
        self.clear()
        self.origin = tuple(logical)
        self.last_x = self.extreme = logical[0]

    def move(self, logical, now):
        if not self.active:
            return None
        if math.dist(self.origin,logical) > RUB_REACH:
            self.direction = 0
            self.reversals = ()
            self.tickling = False
            self.last_x = self.extreme = logical[0]
            return 'pause'
        x = logical[0]
        began = False
        if not self.direction:
            if abs(x-self.extreme) >= REVERSE_DISTANCE:
                self.direction = 1 if x > self.extreme else -1
                self.extreme = x
        elif (x-self.extreme)*self.direction >= 0:
            self.extreme = x
        elif abs(x-self.extreme) >= REVERSE_DISTANCE:
            self.direction *= -1
            self.extreme = x
            self.reversals = tuple(t for t in self.reversals if now-REVERSE_WINDOW <= t <= now)+(now,)
            if len(self.reversals) >= REVERSE_COUNT:
                began = not self.tickling
                self.tickling = True
        if began or abs(x-self.last_x) >= MOVE_EPSILON:
            self.last_x = x
            return 'tickle' if self.tickling else None
        return None

    def clear(self):
        self.origin = None
        self.last_x = self.extreme = 0.
        self.direction = 0
        self.reversals = ()
        self.tickling = False


@dataclass(frozen=True)
class TickleState:
    base: str | None = None
    owns_face: bool = True
    stage: str = 'idle'
    face: str | None = None
    fade: float = 0.
    started_at: float = 0.
    last_move: float = 0.
    updated_at: float = 0.
    released_at: float | None = None
    body: Spring = field(default_factory=Spring)
    arm: Spring = field(default_factory=Spring)
    head: Spring = field(default_factory=Spring)
    drop: Spring = field(default_factory=Spring)
    torso: Spring = field(default_factory=Spring)

    @property
    def active(self):
        return self.base is not None


def stroke_tickle(state, now, expression):
    if not state.active or not state.owns_face:
        state = replace(state,base=expression,owns_face=True,started_at=now,updated_at=now)
    return replace(state,last_move=now,released_at=None,stage='tickle',face='happy',fade=0.)


def release_tickle(state, now):
    if not state.active or state.released_at is not None:
        return state
    return replace(state,released_at=now)


def step_tickle(state, now):
    if not state.active:
        return state
    dt = max(0.,now-state.updated_at)
    stop = min(state.last_move+STOP_DELAY,
               state.released_at if state.released_at is not None else math.inf)
    quiet = max(0.,now-stop)
    if now >= stop and (quiet >= SETTLE_TIME+AFTER_HOLD+FADE_TIME
                        or (not state.owns_face and quiet >= SETTLE_TIME)):
        return TickleState()
    moving = now < stop
    phase = (now-state.started_at)*math.tau
    body_target = .008*(.5+.5*math.sin(phase*5.5)) if moving else 0.
    arm_target = -5.+4.*math.sin(phase*3.5) if moving else 0.
    head_target = .65*math.sin(phase*2.5) if moving else 0.
    torso_target = 1.8*math.sin(phase*2.5) if moving else 0.
    u = max(0.,min(1.,(quiet-SETTLE_TIME-AFTER_HOLD)/FADE_TIME))
    stage = ('tickle' if moving else 'settle' if quiet < SETTLE_TIME
             else 'hold' if quiet < SETTLE_TIME+AFTER_HOLD else 'fade')
    return replace(state,updated_at=now,stage=stage,fade=u*u*(3-2*u),
                   body=spring_step(state.body,dt,body_target,4.,.7),
                   arm=spring_step(state.arm,dt,arm_target,4.,.7),
                   head=spring_step(state.head,dt,head_target,4.,.7),
                   drop=spring_step(state.drop,dt,0.,4.,.7),
                   torso=spring_step(state.torso,dt,torso_target,4.,.7))
