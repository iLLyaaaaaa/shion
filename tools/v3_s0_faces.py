"""S6：用 S0 切片部件（parts/eye_half_*、mouth_*）拼出新的 V3 表情，写进 rig.json。

python -m tools.v3_s0_faces      # 然后：python -m tools.v3_cheek

- tired（slump 疲惫）：neutral 底 + 半闭眼
- bored（neglect1 无聊）：neutral 底 + 半闭眼 + 波浪嘴
- yawn（哈欠）：sleep 底 + 张大嘴（再放大 YAWN_SCALE 倍）

S0 部件和现五官比例不同，按 “现 neutral 眼宽 / S0 睁眼宽”“现 neutral 嘴宽 / S0 微笑嘴宽” 缩放，
以底表情对应五官的中心为中心摆放。没换的五官原样复制底表情的图。
重复运行结果相同（已有同名表情会被覆盖）。之后必须运行 tools.v3_cheek 重建捏脸素材。
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from PIL import Image

from v3proto.render import DEFAULT_RIG

PARTS = Path("assets/sprites/v3/parts")
EYE_K = 183 / 118    # 现 neutral 眼宽（expr_neutral_eye_l）/ S0 eye_open_l 宽
MOUTH_K = 33 / 80    # 现 neutral 嘴宽（expr_neutral_mouth）/ S0 mouth_smile 宽
HALF_EYES = {"eye_l": ("eye_half_l", EYE_K), "eye_r": ("eye_half_r", EYE_K)}
YAWN_SCALE = 1.8     # 用户 2026-11-10 在 1.6 / 1.8 对比里选 1.8
FACES = {
    "tired": ("neutral", HALF_EYES),
    "bored": ("neutral", {**HALF_EYES, "mouth": ("mouth_wavy", MOUTH_K)}),
    "yawn": ("sleep", {"mouth": ("mouth_open_big", MOUTH_K * YAWN_SCALE)}),
}
ROLES = ("eye_l", "eye_r", "mouth")


def _s0(name: str, k: float) -> Image.Image:
    with Image.open(PARTS / f"{name}.png") as im:
        image = im.convert("RGBA")
    return image.resize((round(image.width * k), round(image.height * k)), Image.Resampling.LANCZOS)


def build(faces=FACES, rig_path=DEFAULT_RIG) -> dict:
    rig_path = Path(rig_path)
    data = json.loads(rig_path.read_text(encoding="utf-8"))
    parts = data["parts"]
    folder = rig_path.parent
    made = {}
    for face, (base, swaps) in faces.items():
        for role in ROLES:
            base_name = f"expr_{base}_{role}"
            entry = copy.deepcopy(parts[base_name])
            with Image.open(folder / entry["file"]) as im:
                image = im.convert("RGBA")
            if role in swaps:
                cx = entry["x"] + entry["size"][0] / 2
                cy = entry["y"] + entry["size"][1] / 2
                image = _s0(*swaps[role])
                entry["x"], entry["y"] = round(cx - image.width / 2), round(cy - image.height / 2)
                entry["size"] = [image.width, image.height]
                if role.startswith("eye"):
                    # 眨眼往下合到眼睛底边（与现有表情一致：底边上 1 像素）
                    entry["blink_pivot"] = [cx, entry["y"] + image.height - 1]
                entry["source"] = "s0_part"
            name = f"expr_{face}_{role}"
            entry["file"] = f"expressions/{name}.png"
            entry["variant"] = face
            image.save(folder / entry["file"])
            parts[name] = entry
        data["faces"][face] = {"face": face}
        if face not in data["slots"]["face"]:
            data["slots"]["face"].append(face)
        made[face] = base
    # 捏脸素材要覆盖全部表情，否则 Rig 拒绝加载；先拿掉，由 tools.v3_cheek 整体重建（配置是常量）
    data.get("interactions", {}).pop("cheek_left", None)
    rig_path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return made


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.parse_args(argv)
    print("built", build(FACES))


if __name__ == "__main__":
    main()
