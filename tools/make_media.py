r"""确定性离屏生成 README 媒体，不读取桌面、用户存档或 Claude 设置。

运行：.venv\Scripts\python tools\make_media.py
相同 Windows / 字体 / Python / Qt / Pillow 下输出逐字节相同；跨版本不保证。
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path
import platform
import sys
import tempfile

from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEED = 42
SCALE = 2
FPS = 20
FRAME_COUNT = 80
HERO_SIZE = (480, 360)
STILL_SIZE = (720, 420)
FONTS = {"zh": "Microsoft YaHei UI", "en": "Cascadia Mono", "ja": "Yu Gothic UI"}
NAMES = ("hero.gif", "pat.png", "desk.png", "permission.zh.png", "permission.en.png",
         "permission.ja.png", "sleep-bed.png")
GIF_LIMIT, PNG_LIMIT, TOTAL_LIMIT = 2_000_000, 300_000, 5_000_000


def media_application():
    """在导入 GUI 前固定环境；复用既有 QApplication，不启动事件循环。"""
    if sys.platform == "win32":
        os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_SCALE_FACTOR"] = "1"
    os.environ["QT_SCREEN_SCALE_FACTORS"] = "1"
    os.environ["QT_FONT_DPI"] = "96"
    from PySide6.QtCore import QLocale
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["make_media"])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())
    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    available = set(QFontDatabase.families())
    missing = sorted(set(FONTS.values()) - available)
    if missing:
        raise RuntimeError("缺少固定字体：" + ", ".join(missing))
    font = QFont(FONTS["en"])
    font.setPixelSize(13)
    app.setFont(font)
    return app


def pil_image(image) -> Image.Image:
    from PySide6.QtGui import QImage
    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombytes("RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()),
                           "raw", "RGBA", rgba.bytesPerLine()).copy()


def card(image, size: tuple[int, int], *, crop: bool = True) -> Image.Image:
    """返回 2x RGB 卡片；所有内容在降采样前合成，英雄图保留固定脚底锚点。"""
    content = pil_image(image)
    if crop:
        bounds = content.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError("场景为空")
        content = content.crop(bounds)
    width, height = (n * SCALE for n in size)
    if content.width > width - 40 * SCALE or content.height > height - 40 * SCALE:
        raise ValueError(f"场景超出卡片安全区：{content.size} -> {size}")
    canvas = Image.new("RGB", (width, height), "#EEEAE5")
    draw = ImageDraw.Draw(canvas)
    inset = 8 * SCALE
    draw.rounded_rectangle((inset, inset, width - inset - 1, height - inset - 1),
                           radius=20 * SCALE, fill="#FAF8F5", outline="#D9D1C7", width=SCALE)
    canvas.paste(content, ((width - content.width) // 2, (height - content.height) // 2), content)
    return canvas


def downsample(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.LANCZOS)


def hero_frames() -> list[Image.Image]:
    from shion.animator import BLINK_DURATION, ease_out
    from shion.app import SnapshotScene

    frames = []
    with SnapshotScene(height=260, activity="quiet", seed=SEED, scale=SCALE) as scene:
        win = scene.win
        win._animator._next_blink = math.inf
        first = None
        for index in range(FRAME_COUNT):
            elapsed = index / FPS
            scene.advance_to(elapsed)
            if index == 8:
                win._animator._blinks = [(scene.time[0], scene.time[0] + BLINK_DURATION)]
                win.advance_to(scene.time[0])
            elif index == 16:
                win.jump()
            elif index == 27:
                win.set_state("happy")
            elif index == 42:
                win.set_state("idle")
                win._animator._next_blink = math.inf
            image = card(scene.render(), HERO_SIZE, crop=False)
            if first is None:
                first = image.copy()
            if elapsed >= 3.6:
                image = Image.blend(image, first, ease_out(min(1.0, (elapsed - 3.6) / .2)))
            frames.append(downsample(image, HERO_SIZE))
    return frames


def pat_image():
    import random
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QPainter
    from shion.app import SnapshotScene, render_widget_image
    from shion.effects import HeartOverlay

    with SnapshotScene("happy", height=260, activity="quiet", seed=SEED, scale=SCALE) as scene:
        hearts = HeartOverlay(clock=lambda: scene.time[0], autostart=False, rng=random.Random(SEED))
        hearts.setAttribute(Qt.WA_DontShowOnScreen)
        try:
            for elapsed in (0.0, .2, .4):
                scene.advance_to(elapsed)
                hearts.burst(scene.win.head_anchor(), start_session=elapsed == 0)
            scene.advance_to(.65)
            hearts.tick()
            image = scene.render()
            overlay = render_widget_image(hearts, SCALE)
            painter = QPainter(image)
            painter.drawImage(hearts.pos() - scene.win.pos(), overlay)
            painter.end()
            return image
        finally:
            hearts.close()
            hearts.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def still_images():
    from shion.app import SnapshotScene, render_snapshot_panel

    yield "pat.png", pat_image()
    with SnapshotScene("desk", height=260, seed=SEED, scale=SCALE) as scene:
        scene.advance_to(.3)
        yield "desk.png", scene.render()
    for lang in FONTS:
        yield f"permission.{lang}.png", render_snapshot_panel(
            "permission", text="npm test", lang=lang, with_pet=True, scale=SCALE, fixed_scene=True)
    with SnapshotScene("bed", height=260, seed=SEED, scale=SCALE) as scene:
        for elapsed in (.9, 1.8):
            scene.advance_to(elapsed)
        yield "sleep-bed.png", scene.render()


def write_gif(path: Path, frames: list[Image.Image]) -> None:
    # 整段动画共同量化，避免逐帧调色板闪烁；无随机抽样、无抖动。
    atlas = Image.new("RGB", (HERO_SIZE[0], HERO_SIZE[1] * len(frames)))
    for index, frame in enumerate(frames):
        atlas.paste(frame, (0, index * HERO_SIZE[1]))
    palette = atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    encoded[0].save(path, save_all=True, append_images=encoded[1:], duration=1000 // FPS,
                    loop=0, disposal=1, optimize=False)


def validate_files(directory: Path, other_bytes: int = 0) -> list[dict]:
    report = []
    for name in NAMES:
        path = directory / name
        data = path.read_bytes()
        limit = GIF_LIMIT if name.endswith(".gif") else PNG_LIMIT
        if len(data) > limit:
            raise ValueError(f"{name} 超限：{len(data)} > {limit} 字节")
        with Image.open(path) as image:
            expected = HERO_SIZE if name.endswith(".gif") else STILL_SIZE
            if image.size != expected:
                raise ValueError(f"{name} 尺寸错误：{image.size}")
            if name.endswith(".gif"):
                if image.info.get("loop") != 0:
                    raise ValueError("GIF 必须无限循环")
                first = image.convert("RGB").tobytes()
                duration = 0
                for index in range(image.n_frames):
                    image.seek(index)
                    duration += image.info["duration"]
                if duration != 4000 or image.convert("RGB").tobytes() != first:
                    raise ValueError("GIF 时长或首尾衔接错误")
            elif image.mode != "RGB" or image.info:
                raise ValueError(f"{name} 必须是不带元数据的 RGB PNG")
        report.append({"file": name, "width": expected[0], "height": expected[1],
                       "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    total = sum(item["bytes"] for item in report) + other_bytes
    if total > TOTAL_LIMIT:
        raise ValueError(f"图片目录总体积超限：{total} > {TOTAL_LIMIT} 字节")
    return report


def generate_media(output_dir: Path) -> list[dict]:
    app = media_application()  # 持有强引用，直到这次所有帧/面板均已销毁。
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    other_bytes = sum(p.stat().st_size for p in output_dir.rglob("*")
                      if p.is_file() and p.relative_to(output_dir).as_posix() not in NAMES)
    # 先生成、校验全部七个文件；编码或预算失败不改动已有成品。
    with tempfile.TemporaryDirectory(prefix=".make-media-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        write_gif(staging / "hero.gif", hero_frames())
        for name, image in still_images():
            downsample(card(image, STILL_SIZE), STILL_SIZE).save(staging / name, compress_level=9)
        report = validate_files(staging, other_bytes)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            (staging / name).replace(output_dir / name)
    del app
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "images",
                        help="输出目录（默认仓库 docs/images，仅替换本工具的七个文件）")
    args = parser.parse_args(argv)
    try:
        report = generate_media(args.output_dir)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"media generation failed: {error}", file=sys.stderr)
        return 1
    from PySide6.QtCore import qVersion
    print(f"Python {platform.python_version()} | Qt {qVersion()} | Pillow {PILLOW_VERSION}")
    print("seed=42 clock=100.0 scale=2 fonts=" + ", ".join(FONTS.values()))
    for item in report:
        path = os.path.relpath(args.output_dir / item["file"], ROOT).replace("\\", "/")
        print(f"{path}: {item['width']}x{item['height']}, {item['bytes']} bytes, SHA-256 {item['sha256']}")
    print(f"generated total: {sum(item['bytes'] for item in report)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
