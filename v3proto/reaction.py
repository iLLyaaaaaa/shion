"""Deterministic pinch reactions. Times are injected monotonic seconds."""
from dataclasses import dataclass, field, replace
import math

from .motion import Spring, spring_step


@dataclass(frozen=True)
class ReactionParameters:
    surprise: float = .20
    cry_after: float = 2.0
    cry_fraction: float = .70
    rebound_time: float = 1.0
    after_hold: float = 1.5
    fade: float = .35
    combo_window: float = 10.0
    arm_hz: float = 4.0
    arm_degrees: float = 3.0
    cry_arm_hz: float = 6.0
    cry_arm_degrees: float = 4.5

    def __post_init__(self):
        values = tuple(getattr(self, n) for n in self.__dataclass_fields__)
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise ValueError("reaction parameters must be finite and nonnegative")
        if self.rebound_time <= 0 or not 0 <= self.cry_fraction <= 1:
            raise ValueError("invalid rebound time or cry threshold")


@dataclass(frozen=True)
class ReactionState:
    base: str | None = None
    stage: str = "idle"
    face: str | None = None
    pressed_at: float = 0.
    released_at: float | None = None
    settled_at: float | None = None
    history: tuple = ()
    count: int = 0
    easter: bool = False
    escalated: bool = False
    params: ReactionParameters = field(default_factory=ReactionParameters)
    phase: float = 0.
    arm: Spring = field(default_factory=Spring)
    body: Spring = field(default_factory=Spring)
    head: Spring = field(default_factory=Spring)
    fade: float = 0.
    drop: Spring = field(default_factory=Spring)

    @property
    def active(self):
        return self.base is not None


def press_reaction(state, now, expression, params):
    history = tuple(t for t in state.history if now - params.combo_window <= t <= now) + (now,)
    easter = len(history) >= 3
    return ReactionState(base=state.base or expression, stage="cry" if easter else ("surprise" if params.surprise else "struggle"),
                         face="teary" if easter else ("surprised" if params.surprise else "dizzy"), pressed_at=now,
                         history=history, count=len(history), easter=easter, escalated=easter,
                         params=params, phase=state.phase, arm=state.arm,
                         body=state.body, head=state.head, drop=state.drop)


def release_reaction(state, now):
    if not state.active or state.released_at is not None:
        return state
    return replace(state, stage="rebound", face="teary" if state.easter else "angry",
                   released_at=now)


def step_reaction(state, now, dt, outward_fraction=0., settled=False, cheek_velocity=0.):
    """Advance the phase and secondary springs without reading clocks or UI."""
    if dt < 0:
        raise ValueError("time must advance")
    if not state.active:
        return state
    p = state.params
    age = max(0., now - state.pressed_at)
    escalated = state.escalated or age > p.cry_after or outward_fraction > p.cry_fraction
    stage, face, settled_at, fade = state.stage, state.face, state.settled_at, 0.
    if state.released_at is None:
        if state.easter or (age >= p.surprise and escalated):
            stage, face = "cry", "teary"
        elif age < p.surprise:
            stage, face = "surprise", "surprised"
        else:
            stage, face = "struggle", "dizzy"
    else:
        if settled and settled_at is None:
            settled_at = now
        stage = "rebound" if settled_at is None else "hold"
        if settled_at is not None and now >= settled_at + p.after_hold:
            stage = "fade"
            u = 1. if p.fade == 0 else min(1., (now - settled_at - p.after_hold) / p.fade)
            fade = u * u * (3 - 2 * u)
            if u >= 1:
                return ReactionState(history=state.history, count=state.count)
    struggling = stage in ("struggle", "cry")
    hz = p.cry_arm_hz if stage == "cry" else p.arm_hz
    amplitude = p.cry_arm_degrees if stage == "cry" else p.arm_degrees
    phase = state.phase + math.tau * hz * dt if struggling else state.phase
    arm_target = amplitude * math.sin(phase) if struggling else 0.
    # Exact springs keep stage changes and early release continuous.
    arm = spring_step(state.arm, dt, arm_target, frequency=12, damping=.65)
    pulse = .015 * math.sin(math.pi * min(1., age / max(p.surprise, .001))) if stage == "surprise" else 0.
    body = spring_step(state.body, dt, pulse, frequency=10, damping=.6)
    head_target = 1.2 * math.tanh(cheek_velocity / 650.) if stage == "rebound" else 0.
    head = spring_step(state.head, dt, head_target, frequency=3, damping=.7)
    drop = spring_step(state.drop, dt, 0., frequency=14, damping=.75)
    return replace(state, stage=stage, face=face, escalated=escalated, settled_at=settled_at,
                   phase=phase, arm=arm, body=body, head=head, drop=drop, fade=fade)
