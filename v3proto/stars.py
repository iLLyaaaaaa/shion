"""Random launches sampled once per click; ballistic motion sampled at render time."""
from dataclasses import dataclass
import math
import random

STAR_LIFETIME = 1.10
STAR_MIN_COUNT = 6
STAR_COUNT = 10
MAX_STAR_BURSTS = 3
STAR_GRAVITY = 900.0  # Reference pixels / second squared.
STAR_RADIUS_RANGE = (36.0,44.0)  # Expanded star is slightly smaller than the palm.


@dataclass(frozen=True)
class Launch:
    vx: float
    vy: float
    radius: float
    rotation: float
    spin: float
    life: float
    birth: float


@dataclass(frozen=True)
class StarBurst:
    origin: tuple
    launches: tuple


def make_star_burst(origin, rng):
    count = rng.randint(STAR_MIN_COUNT,STAR_COUNT)
    launches = []
    for i in range(count):
        # Stratify the fan so random samples do not all choose the same direction.
        angle = math.radians(-155+(i+rng.uniform(.15,.85))*130/count)
        speed = rng.uniform(280,460)
        launches.append(Launch(math.cos(angle)*speed,math.sin(angle)*speed,
                               rng.uniform(*STAR_RADIUS_RANGE),rng.uniform(-180,180),rng.uniform(-240,240),
                               rng.uniform(.88,1.05),rng.uniform(0,.035)))
    return StarBurst(tuple(float(v) for v in origin),tuple(launches))


DEFAULT_STAR_BURST = make_star_burst((500.,150.),random.Random(0))


@dataclass(frozen=True)
class Star:
    x: float
    y: float
    radius: float
    rotation: float
    opacity: float


def star_particles(age, burst=DEFAULT_STAR_BURST):
    if age is None or not 0 <= age < STAR_LIFETIME:
        return ()
    particles = []
    def smooth(value):
        value = min(1., max(0., value))
        return value*value*(3-2*value)

    for launch in burst.launches:
        elapsed = age-launch.birth
        if not 0 <= elapsed < launch.life:
            continue
        u = elapsed/launch.life
        x = launch.vx*elapsed
        y = launch.vy*elapsed+.5*STAR_GRAVITY*elapsed*elapsed
        radius = launch.radius*(.55+.45*smooth(elapsed/.06))*(1-.35*smooth((u-.55)/.45))
        opacity = smooth(elapsed/.045)*(1-smooth((u-.58)/.42))
        particles.append(Star(x,y,radius,launch.rotation+launch.spin*elapsed,opacity))
    return tuple(particles)


def paint_stars(image, rig, scale, pose, offset=(0,0)):
    particles = [(star,burst.origin) for age,burst in pose.star_effects
                 for star in star_particles(age,burst)]
    if not particles:
        return image
    from PySide6.QtCore import Qt,QRectF
    from PySide6.QtGui import QColor,QPainter,QPainterPath,QPen,QLinearGradient,QRadialGradient
    result = image.copy()  # Never paint into a cached rig frame.
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale,scale)
    painter.translate(*offset)
    for star,anchor in particles:
        painter.save()
        painter.setOpacity(star.opacity)
        painter.translate(anchor[0]+star.x,anchor[1]+star.y)
        painter.rotate(star.rotation)
        halo = star.radius*1.6
        glow = QRadialGradient(0,0,halo)
        glow.setColorAt(0,QColor(255,229,137,38))
        glow.setColorAt(1,QColor(255,229,137,0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-halo,-halo,halo*2,halo*2))
        path = QPainterPath()
        for k in range(10):
            angle = -math.pi/2+k*math.pi/5
            radius = star.radius*(1 if k%2==0 else .46)
            x,y = radius*math.cos(angle),radius*math.sin(angle)
            if k==0:path.moveTo(x,y)
            else:path.lineTo(x,y)
        path.closeSubpath()
        gold = QLinearGradient(-star.radius,-star.radius,star.radius,star.radius)
        gold.setColorAt(0,QColor('#FFF4A2'))
        gold.setColorAt(.45,QColor('#FFE26B'))
        gold.setColorAt(1,QColor('#F5BE36'))
        painter.setPen(QPen(QColor('#DDA12D'),.8))
        painter.setBrush(gold)
        painter.drawPath(path)
        painter.restore()
    painter.end()
    return result
