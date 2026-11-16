"""V3 姿势变体（scene：collapse / bed / desk）的纯逻辑，不依赖 Qt。

三张整图（assets/sprites/v3/scenes/，由 tools/v3_scene.py 生成）各是一个“姿势变体”，不拆零件。
图已经缩放到站姿的 rig 比例，所以 scene 像素 ≈ rig 像素；地面线（ground_y）对齐脚底线，
水平中心（anchor_x）对齐脚底中心，现有的窗口 ← rig 坐标换算原样可用。

分层（家具看得见但点不到，呼吸时角色和家具之间不能露透明缝，敲头时不能留下不动的描线）：
- under：垫在最底下，**只有家具颜色**：角色像素里离家具不远的那些，换成最近的家具像素的颜色（家具往角色底下
  延伸一圈），再加上被家具层挖掉的那圈 FURNITURE_GAP 家具像素。角色层缩回去时露出来的是家具，不是不动的角色；
  没有家具（collapse）就没有 under；
- char：只有角色像素，呼吸/摸头/敲头时绕地面支点做仿射，画在 under 上面；
- furniture：整图去掉角色周围 FURNITURE_GAP 像素，画在点穿的覆盖窗里，盖在角色前面；
- 诗音窗口的遮罩 = 变形后的角色 ∪ under 的轮廓，再外扩；家具本体不进遮罩，所以点得穿。
- 带宽随离地高度变宽（seam_reach）：同样缩 x%，越高的地方位移越大。
- 家具层不跟 V2 的整体压扁/倾斜走：scene 里只取点击压扁的 POKE_SHARE。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCENES_ENV = "SHION_V3_SCENES"          # 设为 0：不用 scene，回到站姿回退
SCENES_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites" / "v3" / "scenes"
SCENES_JSON = SCENES_DIR / "scenes.json"
ENTER_POP = (0.24, 0.97)                 # 进入/换 scene 时的小弹跳：(时长 秒, 最扁 sy)，同 animator 的“switch”压扁
SCENE_PAD = 60                           # rig 像素：scene 帧四周留的透明边（倾斜、金星用）
KNOCK_SQUASH = 0.02                      # 敲头：整图最多下压 2%
KNOCK_HEAD_Y = 28.0                      # 敲头下沉 28 rig 像素 = 满压
PAT_TILT = 0.4                           # 摸头：整图倾斜 = 头部倾斜 × 0.4（±2.5° → ±1°）
FURNITURE_GAP = 2                        # 家具图里去掉角色周围这么宽的一圈（同 tools/v3_scene.py）
FURNITURE_MIN_PIXELS = 500               # 家具像素少于这个：算没有家具（collapse），不建覆盖窗
HIT_ALPHA = 64                           # 命中：角色 alpha 要超过这个（同 V3 其它命中）
WINDOW_MARGIN = 16                       # rig 像素：窗口宽度在角色半宽之外多留的余量
POKE_SHARE = 0.25                        # V2 点击压扁（最深 0.92）在 scene 里只取这么多：最多压 2%
SEAM_MARGIN = 6                          # rig 像素：垫底带宽的固定部分
FILL_LUMA = 70                           # 垫底取色：家具里比这更亮的才算“底色”（描线是深色，延伸出去会成一个深色楔子）
SEAM_SHRINK = 0.08                       # 垫底带宽随离地高度增加的比例（角色层最多缩回/横移的上限：弹跳 3% + 敲头 2% + 点击 2% + 摸头 1°）


@dataclass(frozen=True)
class Scene:
    name: str
    file: str
    mask: str
    size: tuple[int, int]
    anchor_x: float
    ground_y: float
    char_box: tuple[int, int, int, int]
    head_scale: float
    head_top: tuple[float, float]
    mouth: tuple[float, float]
    z_anchor: tuple[float, float] | None
    cheek: tuple[tuple[float, float, float, float], ...]
    crown: tuple[tuple[float, float, float, float], ...]
    breath_gain: float
    furniture_pixels: int

    @property
    def has_furniture(self) -> bool:
        return self.furniture_pixels >= FURNITURE_MIN_PIXELS


def load_metadata(path: Path | None = None, env=None) -> dict[str, Scene] | None:
    """状态名 → Scene。SHION_V3_SCENES=0 或 scenes.json 不存在时返回 None（不用 scene）。"""
    env = os.environ if env is None else env
    if env.get(SCENES_ENV) == "0":
        return None
    path = Path(path) if path is not None else SCENES_JSON
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    scenes = {}
    for name, info in data["scenes"].items():
        scenes[name] = Scene(
            name=name, file=info["file"], mask=info["mask"], size=tuple(info["size"]),
            anchor_x=float(info["anchor_x"]), ground_y=float(info["ground_y"]),
            char_box=tuple(info["char_box"]), head_scale=float(info["head_scale"]),
            head_top=tuple(info["head_top"]), mouth=tuple(info["mouth"]),
            z_anchor=tuple(info["z_anchor"]) if "z_anchor" in info else None,
            cheek=tuple(tuple(e) for e in info["zones"]["cheek"]),
            crown=tuple(tuple(e) for e in info["zones"]["crown"]),
            breath_gain=float(info["breath_gain"]), furniture_pixels=int(info["furniture_pixels"]))
    return {state: scenes[target] for state, target in data["states"].items()}


def scene_for(state: str, scenes: dict[str, Scene] | None) -> Scene | None:
    return None if scenes is None else scenes.get(state)


# ---- 坐标（scene 像素 ↔ rig 像素；foot 是 rig.v3_foot = (脚底中心 x, 脚底 y)）----
def to_scene(scene: Scene, rig_point, foot) -> tuple[float, float]:
    return (rig_point[0] - foot[0] + scene.anchor_x, rig_point[1] - foot[1] + scene.ground_y)


def to_rig(scene: Scene, scene_point, foot) -> tuple[float, float]:
    return (scene_point[0] - scene.anchor_x + foot[0], scene_point[1] - scene.ground_y + foot[1])


def extra_half_width(scene: Scene) -> float:
    """角色相对 anchor_x 的最大半宽 + 余量（rig 像素）：窗口至少要这么宽才放得下。"""
    x0, _, x1, _ = scene.char_box
    return max(scene.anchor_x - x0, x1 - scene.anchor_x) + WINDOW_MARGIN


# ---- 仿射：呼吸、敲头下压、摸头倾斜，支点 = 地面线上的 anchor 点（scene 像素）----
def poke_scale(frame_sy: float) -> float:
    """V2 帧的纵向缩放（点击/切换压扁及回弹）→ scene 里的一小部分，角色最多缩回 2%。"""
    return 1.0 + (frame_sy - 1.0) * POKE_SHARE


def enter_pop(elapsed: float) -> float:
    """进入/换 scene 后 elapsed 秒的纵向缩放：压到 ENTER_POP[1] 再轻微回弹，结束后精确为 1.0（曲线同 animator.squash_scale）。"""
    dur, low = ENTER_POP
    if elapsed <= 0 or elapsed >= dur:
        return 1.0
    p, depth = elapsed / dur, 1.0 - low
    if p < 0.6:
        return 1.0 - depth * math.sin(math.pi * p / 0.6)
    return 1.0 + 0.3 * depth * math.sin(math.pi * (p - 0.6) / 0.4)


def scene_affine(scene: Scene, body_scale: float, head_y: float, head_roll: float,
                 poke: float = 1.0, pop: float = 1.0) -> tuple[float, float]:
    """(纵向缩放 sy, 倾斜角度)。body_scale 是动画器的呼吸缩放（1～1.012），head_y 是敲头下沉量，
    poke 是 poke_scale(V2 帧的 sy)，pop 是 enter_pop(进入后经过的秒数)。"""
    sy = 1.0 + (body_scale - 1.0) * scene.breath_gain
    squash = min(1.0, max(0.0, head_y / KNOCK_HEAD_Y))
    return sy * (1.0 - KNOCK_SQUASH * squash) * poke * pop, head_roll * PAT_TILT


def affine_matrix(scene: Scene, sy: float, angle: float) -> np.ndarray:
    """scene 像素 → 变形后的 scene 像素：平移到支点、先纵向缩放再旋转（同 Qt translate/rotate/scale 顺序）。"""
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    linear = np.array([[c, -s * sy], [s, c * sy]])
    pivot = np.array([scene.anchor_x, scene.ground_y])
    m = np.eye(3)
    m[:2, :2] = linear
    m[:2, 2] = pivot - linear @ pivot
    return m


def to_rest(scene: Scene, point, sy: float, angle: float) -> tuple[float, float]:
    """变形后画面上的点 → 静止图上的点（命中用）。"""
    inverse = np.linalg.inv(affine_matrix(scene, sy, angle))
    x, y, _ = inverse @ np.array([point[0], point[1], 1.0])
    return float(x), float(y)


# ---- 命中分区 ----
class ArrayMask:
    """角色遮罩数组 + 它和 scene 像素的换算（scale：数组像素 / scene 像素；pad：数组左上角在 scene 里的偏移取负）。"""

    def __init__(self, alpha: np.ndarray, scale: float = 1.0, pad: float = 0.0, threshold: int = HIT_ALPHA):
        self.alpha, self.scale, self.pad, self.threshold = alpha, scale, pad, threshold

    def contains(self, x: float, y: float) -> bool:
        ix, iy = int(math.floor((x + self.pad) * self.scale)), int(math.floor((y + self.pad) * self.scale))
        h, w = self.alpha.shape[:2]
        return 0 <= ix < w and 0 <= iy < h and int(self.alpha[iy, ix]) > self.threshold


def in_ellipse(e, x: float, y: float) -> bool:
    cx, cy, rx, ry = e
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def zone_at(scene: Scene, x: float, y: float, mask) -> str | None:
    """静止图上的点 → None（透明或家具）/ "cheek"（拎起把手）/ "crown"（摸头敲头）/ "body"（戳）。"""
    if not mask.contains(x, y):
        return None
    if any(in_ellipse(e, x, y) for e in scene.cheek):
        return "cheek"
    if any(in_ellipse(e, x, y) for e in scene.crown):
        return "crown"
    return "body"


def scene_draw_key(scene: Scene, w: float, sy: float, angle: float, texture_scale: float, stars: bool):
    """量化后的“这一帧 scene 长什么样”；没变就不必重画。有金星时返回 None（每帧都在动）。"""
    if stars:
        return None
    quantum = 0.25 / max(scene.size[1] * texture_scale, 1.0)   # 纵向变化 0.25 设备像素
    return (scene.name, round(w / 0.02), round((sy - 1.0) / quantum), round(angle / 0.1))


# ---- 载入（三张图 → 按纹理比例缩好的预乘数组）----
def _premultiply(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.uint16)
    rgb = (rgba[..., :3].astype(np.uint16) * a + 127) // 255
    return np.concatenate([rgb.astype(np.uint8), rgba[..., 3:4]], axis=-1)


def split_layers(image: np.ndarray, char: np.ndarray):
    """(full, char_layer, furniture) 三张 RGBA（未缩放，straight alpha）。

    full 就是整张图；char_layer 只留角色像素；furniture 去掉角色周围 FURNITURE_GAP 像素。
    """
    from scipy import ndimage as nd
    char = char.astype(bool)
    full = image.copy()
    char_layer = image.copy()
    char_layer[..., 3] = np.where(char, image[..., 3], 0)
    keep = ~nd.binary_dilation(char, iterations=FURNITURE_GAP)
    furniture = image.copy()
    furniture[..., 3] = np.where(keep, image[..., 3], 0)
    return full, char_layer, furniture


def seam_reach(height_rig: float) -> float:
    """离地 height_rig（rig 像素）处，垫底要延伸的宽度（rig 像素）：角色层缩回 SEAM_SHRINK 时那里的位移 + 固定余量。"""
    return SEAM_MARGIN + SEAM_SHRINK * max(0.0, height_rig)


def under_layer(full: np.ndarray, char: np.ndarray, furniture: np.ndarray, scale: float, ground_row: float):
    """(under 预乘 RGBA 或 None, seam alpha：under 里属于角色一侧的部分，只用来建遮罩)。三张输入都是已缩好的预乘数组，同尺寸。

    - 角色像素里离家具（不透明的家具层像素）不超过 seam_reach 的：取最近的家具底色像素（不含深色描线）的颜色——家具往角色底下延伸；
    - 被家具层挖掉的那圈（整图里可见、既不是角色也不在家具层里），以及圈外侧几个像素的家具：原样放进来；
    - 没有家具：返回 (None, 全 0)。
    """
    from scipy import ndimage as nd
    solid = furniture[..., 3] >= 250
    zero = np.zeros(solid.shape, np.uint8)
    if not solid.any():
        return None, zero
    dist = nd.distance_transform_edt(~solid)
    luma = 0.3 * furniture[..., 0] + 0.59 * furniture[..., 1] + 0.11 * furniture[..., 2]
    fill = solid & (luma > FILL_LUMA)                           # 取色只用家具的底色，不用深色描线
    _, (iy, ix) = nd.distance_transform_edt(~(fill if fill.any() else solid), return_indices=True)
    rows = np.arange(solid.shape[0], dtype=np.float64)
    reach = np.array([seam_reach((ground_row - r) / scale) * scale for r in rows])[:, None]
    char_visible = char[..., 3] > 8
    near = char_visible & (dist <= reach)
    under = np.zeros_like(furniture)
    under[near, :3] = furniture[iy[near], ix[near], :3]
    under[near, 3] = 255
    around = nd.binary_dilation(char_visible, iterations=math.ceil((FURNITURE_GAP + 3) * scale) + 1)
    ring = (full[..., 3] > 8) & around & ~char_visible & (furniture[..., 3] <= 8)   # 只在角色周围：别处的 1～8 级淡雾不算
    under[ring] = full[ring]
    seam = np.ascontiguousarray(under[..., 3])                  # 遮罩只含角色一侧和那圈：不含下面补的家具像素
    # 挖掉的那圈两侧的家具像素也垫一份：覆盖窗和垫底在小数像素位置上各自插值，圈边上的像素才不会比周围透明几级
    edge = nd.binary_dilation(char_visible, iterations=math.ceil((FURNITURE_GAP + 4) * scale) + 1) & (furniture[..., 3] > 8)
    under[edge] = furniture[edge]
    return under, seam


def load_arrays(scene: Scene, texture_scale: float, root: Path | None = None) -> dict:
    """PIL 读图 → 补 SCENE_PAD 透明边 → LANCZOS 缩到纹理比例 → 预乘。

    返回 under（垫底，只有家具颜色；没有家具时为 None）、char / furniture（H×W×4 预乘 uint8）、
    alpha（角色 alpha，H×W uint8，命中用）、seam（under 的 alpha，建遮罩用；没有家具时全 0）、
    scale（实际比例 = 数组像素 / rig 像素）、pad、size（数组宽高）。
    数组左上角在 scene 坐标里是 (-pad, -pad)。
    """
    from PIL import Image
    root = Path(root) if root is not None else SCENES_DIR
    with Image.open(root / scene.file) as im:
        image = np.asarray(im.convert("RGBA"))
    with Image.open(root / scene.mask) as im:
        char = np.asarray(im.convert("L")) > 127
    if image.shape[:2] != char.shape:
        raise ValueError(f"scene 图与遮罩尺寸不一致：{scene.name}")
    layers = split_layers(image, char)
    padded = (image.shape[1] + 2 * SCENE_PAD, image.shape[0] + 2 * SCENE_PAD)
    target = (max(1, round(padded[0] * texture_scale)), max(1, round(padded[1] * texture_scale)))
    out = {}
    for key, layer in zip(("full", "char", "furniture"), layers):
        canvas = Image.new("RGBA", padded)
        canvas.paste(Image.fromarray(layer), (SCENE_PAD, SCENE_PAD))
        if target != padded:
            canvas = canvas.resize(target, Image.Resampling.LANCZOS)
        out[key] = _premultiply(np.asarray(canvas))
    out["alpha"] = np.ascontiguousarray(out["char"][..., 3])
    out["scale"] = target[0] / padded[0]
    full = out.pop("full")                                   # 只用来算 under，不保留
    ground_row = (SCENE_PAD + scene.ground_y) * out["scale"]
    out["under"], out["seam"] = under_layer(full, out["char"], out["furniture"], out["scale"], ground_row)
    out["pad"] = float(SCENE_PAD)
    out["size"] = target
    return out


__all__ = ["Scene", "load_metadata", "scene_for", "to_scene", "to_rig", "extra_half_width", "scene_affine",
           "enter_pop", "ENTER_POP", "affine_matrix", "to_rest", "poke_scale", "seam_reach", "under_layer",
           "SEAM_MARGIN", "SEAM_SHRINK", "FILL_LUMA", "POKE_SHARE", "ArrayMask", "zone_at", "scene_draw_key", "split_layers",
           "load_arrays", "SCENE_PAD", "SCENES_ENV", "FURNITURE_GAP"]
