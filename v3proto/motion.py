"""Pure motion mathematics. Coordinates are reference pixels, time is seconds."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class Spring:
    position: float = 0.0
    velocity: float = 0.0


def spring_step(s: Spring, dt: float, target: float = 0.0,
                frequency: float = 3.0, damping: float = 0.3) -> Spring:
    """Exact underdamped response for a target held constant during this step."""
    if dt < 0 or frequency <= 0 or not 0 <= damping < 1:
        raise ValueError("invalid spring parameters")
    w = 2 * math.pi * frequency
    a = damping * w
    b = w * math.sqrt(1 - damping * damping)
    x = s.position - target
    c, sn, decay = math.cos(b * dt), math.sin(b * dt), math.exp(-a * dt)
    return Spring(target + decay * (x * c + (s.velocity + a * x) * sn / b),
                  decay * (s.velocity * c - (a * s.velocity + w * w * x) * sn / b))


def limit_vector(vector, maximum: float) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float64)
    length = float(np.linalg.norm(v))
    return v * min(1.0, max(0.0, maximum) / max(length, 1e-12))


def release_step(displacement, velocity, dt: float, maximum: float):
    states = [spring_step(Spring(float(x), float(v)), dt)
              for x, v in zip(displacement, velocity)]
    raw = np.array([s.position for s in states])
    pos = limit_vector(raw, maximum)
    vel = np.array([s.velocity for s in states])
    if np.linalg.norm(raw) > maximum:
        normal = pos / max(maximum, 1e-12)
        vel -= max(0.0, float(vel @ normal)) * normal
    if np.linalg.norm(pos) < 0.01 and np.linalg.norm(vel) < 0.05:
        pos[:] = vel[:] = 0
    return pos, vel


def blink_scale(elapsed: float, depth: float = 1.0) -> float:
    """60 ms close + 90 ms open; no overshoot or discontinuity."""
    if not 0 <= elapsed < 0.150:
        return 1.0
    u = elapsed / 0.060 if elapsed < 0.060 else (0.150 - elapsed) / 0.090
    smooth = u * u * (3 - 2 * u)
    return float(1.0 - 0.9 * np.clip(depth, 0, 1) * smooth)


def blink_schedule(rng, duration: float) -> tuple[float, ...]:
    """Caller owns the random generator; ordinary gaps are 3-6 seconds."""
    events = []
    t = float(rng.uniform(3, 6))
    while t < duration:
        events.append(t)
        if rng.random() < 0.15:
            t += 0.24
            if t < duration:
                events.append(t)
        t += float(rng.uniform(3, 6))
    return tuple(events)


def breathing(t: float, amount: float = 1.0, neck_y: float = 664,
              hip_y: float = 1063.4) -> tuple[float, float]:
    """Slightly quicker inhale, relaxed exhale; zero speed at both turnarounds.

    The head follows the body's neck, with only a small secondary lag so the
    large head does not slide independently above the collar.
    """
    def profile(time):
        phase=(time % 3.5)/3.5
        if phase<.42:return .5-.5*math.cos(math.pi*phase/.42)
        return .5+.5*math.cos(math.pi*(phase-.42)/.58)
    q=profile(t)
    scale=1+.012*amount*q
    follow=.85*q+.15*profile(t-.1)
    return scale,(neck_y-hip_y)*.012*amount*follow


def pivot_matrix(pivot, degrees: float = 0, sy: float = 1) -> np.ndarray:
    x, y = pivot
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    m = np.array([[c, -s * sy, 0.0], [s, c * sy, 0.0], [0., 0., 1.]])
    m[:2, 2] = np.array([x, y]) - m[:2, :2] @ np.array([x, y])
    return m


def translation(x: float, y: float) -> np.ndarray:
    return np.array([[1., 0., x], [0., 1., y], [0., 0., 1.]])


def transform_point(matrix, point) -> np.ndarray:
    return (matrix @ np.array([*point, 1.]))[:2]


def bend_inverse(x, y, root, length: float, degrees: float):
    """Continuous horizontal shear: fixed root, quadratic tip displacement."""
    u = np.clip((y - root[1]) / max(length, 1), 0, 1)
    dx = math.tan(math.radians(degrees)) * length * u * u
    return x - dx, y


def rooted_rotation_inverse(x,y,pivot,degrees,polyline,transition=90):
    """Keep the cut's first pixels attached; smoothly rotate the fringe below."""
    poly=np.asarray(polyline,dtype=float)
    sx,sy=x.copy(),y.copy()
    for _ in range(6):
        seam=np.interp(sx,poly[:,0],poly[:,1])
        u=np.clip((sy-seam)/transition,0,1)
        weight=u*u*(3-2*u)
        theta=-np.deg2rad(degrees)*weight
        c,s=np.cos(theta),np.sin(theta)
        sx=pivot[0]+c*(x-pivot[0])-s*(y-pivot[1])
        sy=pivot[1]+s*(x-pivot[0])+c*(y-pivot[1])
    return sx,sy


def pinch_inverse(x, y, center, displacement, radius: float, maximum: float, vertical_bounds=None):
    """Inverse Gaussian flow along the drag path, avoiding folds at 200/60.

    The moving Gaussian center carries the pressed point exactly to its target.
    Midpoint integration keeps the deformation smooth even for large pulls.
    """
    d = limit_vector(displacement, maximum)
    if not np.any(d):
        return x, y
    steps = max(4, int(math.ceil(np.linalg.norm(d) / (radius * 0.15))))
    qx, qy = x.copy(), y.copy()
    h = 1 / steps
    denom = 2 * radius * radius
    def attachment_weight(yy):
        if vertical_bounds is None:
            return 1
        top, bottom = vertical_bounds
        u = np.clip(np.minimum(yy - top, bottom - yy) / 45, 0, 1)
        return u * u * (3 - 2 * u)
    for i in range(steps):
        t = 1 - i * h
        cx, cy = center[0] + t * d[0], center[1] + t * d[1]
        g = np.exp(-((qx - cx) ** 2 + (qy - cy) ** 2) / denom) * attachment_weight(qy)
        mx, my = qx - 0.5 * h * d[0] * g, qy - 0.5 * h * d[1] * g
        cx, cy = cx - 0.5 * h * d[0], cy - 0.5 * h * d[1]
        gm = np.exp(-((mx - cx) ** 2 + (my - cy) ** 2) / denom) * attachment_weight(my)
        qx -= h * d[0] * gm
        qy -= h * d[1] * gm
    return qx, qy


def limit_cheek_drag(vector, maximum: float) -> np.ndarray:
    """Outward pull, small vertical adjustment and a gentle inward press."""
    x, y = np.asarray(vector, dtype=float)
    return limit_vector((np.clip(x, -maximum, 12.), np.clip(y, -24., 24.)), maximum)


def cheek_displacement(vector, maximum: float) -> np.ndarray:
    """Smooth inward rebound saturation; retain the spring's physical state."""
    x, y = np.asarray(vector, dtype=float)
    if x > 0:x = 12 * np.tanh(x / 12)
    return limit_vector((max(-maximum, x), 24 * np.tanh(y / 24)), maximum)


def cheek_weight(x, y, radius: float, region) -> np.ndarray:
    """Rigid rounded end, extensible bridge and pinned root/upper/lower edges."""
    cap, root = region['cap_x'], region['root_x']
    top, upper, lower, bottom = region['vertical']
    t = np.clip((x-cap)/(root-cap), 0, 1)
    bridge = (1-t*t*(3-2*t))*np.exp(-.5*(np.maximum(x-cap,0)/radius)**2)
    a = np.clip((y-top)/(upper-top),0,1)
    b = np.clip((bottom-y)/(bottom-lower),0,1)
    return bridge * (a*a*(3-2*a)) * (b*b*(3-2*b))


def cheek_forward(x, y, displacement, radius: float, region):
    w = cheek_weight(x,y,radius,region)
    return x+displacement[0]*w, y+displacement[1]*w


def cheek_inverse(x, y, displacement, radius: float, region, iterations=18):
    """Invert the rank-one cage along its drag vector with bounded bisection."""
    dx,dy=displacement
    if not dx and not dy:return x,y
    lo=np.zeros_like(x);hi=np.ones_like(x)
    for _ in range(iterations):
        mid=(lo+hi)*.5
        value=mid-cheek_weight(x-dx*mid,y-dy*mid,radius,region)
        lo=np.where(value<0,mid,lo);hi=np.where(value>=0,mid,hi)
    amount=(lo+hi)*.5
    return x-dx*amount,y-dy*amount
