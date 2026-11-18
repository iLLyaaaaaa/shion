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
FRAME_COUNT = 100  # 5 秒：待机眨眼 → 捏脸 → 摸头 → 工作 → 开心跳一下
GIF_DURATION_MS = FRAME_COUNT * 1000 // FPS
PINCH_PIVOT = (325.0, 586.0)  # 左脸颊按下点（与 shion.app.apply_snapshot_gesture 一致）
HERO_SIZE = (480, 360)
STILL_SIZE = (720, 420)
FONTS = {"zh": "Microsoft YaHei UI", "en": "Cascadia Mono", "ja": "Yu Gothic UI"}
WEEKLY_SIZE = (600, 750)
STAMINA_SIZE = (720, 330)
NAMES = ("hero.gif", "pat.png", "pinch.png", "lift.png", "working.png", "side.zh.png", "side.en.png", "side.ja.png", "desk.png",
         "permission.zh.png", "permission.en.png", "permission.ja.png", "sleep-bed.png",
         "weekly.zh.png", "weekly.en.png", "weekly.ja.png",
         "stamina.zh.png", "stamina.en.png", "stamina.ja.png")
GIF_LIMIT, PNG_LIMIT, WEEKLY_LIMIT, TOTAL_LIMIT = 2_000_000, 300_000, 500_000, 6_000_000
# 体力四档按 5 小时额度；配图只用精灵，不读额度数据。
STAMINA_TIERS = (("idle", "< 50%"), ("yawn", "50–80%"), ("slump", "80–95%"), ("collapse", "≥ 95%"))
STAMINA_NAMES = {"zh": ("精神", "打哈欠", "趴下", "倒地"),
                 "en": ("Fresh", "Yawning", "Slumped", "Collapsed"),
                 "ja": ("元気", "あくび", "ぐったり", "ダウン")}
WEEKLY_SEVEN_DAY_PEAK = 68  # 合成的 7 天额度峰值
LIFT_GAP = 40 * SCALE  # lift.png：脚底到“地面”（影子）的距离
CHEEK_POINTS = {"left": (325.0, 586.0), "right": (543.0, 586.0)}  # 脸颊按下点（rig 坐标，同 apply_snapshot_gesture）
# 靠屏幕左半时脸鼓向右（右脸颊鼓），靠右半时鼓向左：左格 = 在屏幕左边 = side "right"。
SIDE_PANELS = (("right", 0), ("left", 1))
SIDE_LABELS = {"zh": ("在屏幕左边", "在屏幕右边"),
               "en": ("Near the left edge", "Near the right edge"),
               "ja": ("画面の左側", "画面の右側")}
ARROW_COLOR = "#B5654A"


def image_size(name: str) -> tuple[int, int]:
    if name.endswith(".gif"):
        return HERO_SIZE
    if name.startswith("weekly."):
        return WEEKLY_SIZE
    if name.startswith("stamina."):
        return STAMINA_SIZE
    return STILL_SIZE


def size_limit(name: str) -> int:
    return GIF_LIMIT if name.endswith(".gif") else WEEKLY_LIMIT if name.startswith("weekly.") else PNG_LIMIT


def _use_inline_prewarm() -> None:
    """配图要逐字节可重复：V3 的预热放在当前线程里做，免得后台线程的快慢决定哪一帧用上预热好的图。"""
    import shion.v3_window as v3_window
    from shion.v3_prewarm import InlineExecutor

    v3_window.PREWARM_EXECUTOR = InlineExecutor()


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
    _use_inline_prewarm()
    return app


def pil_image(image) -> Image.Image:
    if isinstance(image, Image.Image):  # side.png 先在 PIL 里并排，再交给 card()
        return image.convert("RGBA")
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
    """同一个 V3 场景连续取 100 帧（20fps）：待机呼吸 + V3 自己的眨眼 → 捏左脸拉开、松手回弹 →
    摸头冒爱心 → 工作抱电脑点头 → 开心小跳 → 淡回第一帧（首尾逐字节一致，GIF 无缝循环）。
    输入全部走真实窗口的动画器（press / drag / release / stroke_head），不再强塞 V2 动画器的眨眼。"""
    import random
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter
    from shion.animator import ease_out
    from shion.app import SnapshotScene, render_widget_image
    from shion.effects import HeartOverlay

    frames = []
    with SnapshotScene(height=260, activity="quiet", seed=SEED, scale=SCALE) as scene:
        win = scene.win
        animator = win._v3_animator
        hearts = HeartOverlay(clock=lambda: scene.time[0], autostart=False, rng=random.Random(SEED))
        hearts.setAttribute(Qt.WA_DontShowOnScreen)
        try:
            first = None
            for index in range(FRAME_COUNT):
                elapsed = index / FPS
                scene.advance_to(elapsed)
                now = scene.time[0]
                if index == 8:                       # 0.4 秒：让 V3 的眨眼机制马上眨一次
                    animator.blink_start = animator.time + .05
                elif index == 12:                    # 捏左脸颊
                    animator.press(PINCH_PIVOT, now=now)
                if 12 <= index < 30:                 # 0.3 秒内拉开，保持到 1.5 秒
                    reach = min(1.0, (index - 12) / 6)
                    animator.drag((PINCH_PIVOT[0] - 70.0 * reach, PINCH_PIVOT[1]))
                elif index == 30:                    # 松手回弹
                    animator.release(now=now)
                elif index in (44, 48, 52):
                    hearts.burst(win.head_anchor(), start_session=index == 44)
                if 44 <= index < 68:                 # 摸头 1.2 秒
                    animator.stroke_head(1, now=now)
                elif index == 68:
                    animator.release_head(now=now)
                elif index == 70:
                    win.set_state("working")
                elif index == 78:
                    win._animator._nod_at = now
                elif index == 84:
                    win.set_state("happy")
                    win.jump()
                elif index == 92:
                    win.set_state("idle")
                win.advance_to(now)                  # 零时长推进：让上面的输入立刻进入这一帧
                hearts.tick()
                image = scene.render()
                if index >= 44:
                    overlay = render_widget_image(hearts, SCALE)
                    painter = QPainter(image)
                    painter.drawImage(hearts.pos() - win.pos(), overlay)
                    painter.end()
                image = card(image, HERO_SIZE, crop=False)
                if first is None:
                    first = image.copy()
                if elapsed >= 4.7:
                    image = Image.blend(image, first, ease_out(min(1.0, (elapsed - 4.7) / .25)))
                frames.append(downsample(image, HERO_SIZE))
        finally:
            hearts.close()
            hearts.deleteLater()
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


def gesture_image(gesture: str, at: float):
    """真实窗口的 V3 动画器按确定性输入走到手势的第 at 秒（和 --snapshot --gesture 同一入口）。"""
    from shion.app import SnapshotScene, apply_snapshot_gesture

    with SnapshotScene("idle", height=260, activity="quiet", seed=SEED, scale=SCALE) as scene:
        apply_snapshot_gesture(scene.win, gesture, at)
        scene.advance_to(at)
        return scene.render()


def working_image():
    """工作状态：抱着电脑（不带气泡：气泡合成只支持 1x 截图）。"""
    from shion.app import SnapshotScene

    with SnapshotScene("working", height=260, activity="quiet", seed=SEED, scale=SCALE) as scene:
        scene.advance_to(.6)
        return scene.render()


def lift_image():
    """被拎起：人物整体离开“地面”LIFT_GAP 像素，地面处留一个淡影子（窗口移动不在截图里，所以在这里补）。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient

    pet = gesture_image("lift", 1.0).copy()
    pet.setDevicePixelRatio(1)  # 按像素拼接
    left, _, right, bottom = pil_image(pet).getchannel("A").getbbox()
    canvas = QImage(pet.width(), pet.height() + LIFT_GAP, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        radius = (right - left) * .22
        shadow = QRadialGradient(QPointF(0, 0), radius)
        shadow.setColorAt(0, QColor(60, 45, 40, 80))
        shadow.setColorAt(1, QColor(60, 45, 40, 0))
        painter.save()
        painter.translate((left + right) / 2, bottom + LIFT_GAP)
        painter.scale(1.0, 7 * SCALE / radius)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        painter.restore()
        painter.drawImage(0, 0, pet)
    finally:
        painter.end()
    return canvas


def cheek_pixel(win, image_size: tuple[int, int], side: str) -> tuple[float, float]:
    """脸颊按下点在渲染图里的像素位置（窗口：脚底中心 = 画布水平中心；脚底在底边上方 边距 + 脚距）。"""
    from shion.pet_window import MARGIN_BOTTOM
    from shion.v3_display import V2_FOOT_GAP_RATIO

    rx, ry = CHEEK_POINTS[side]
    foot_x, foot_y = win._v3_rig.v3_foot
    ts, dpr = win.v3_texture_scale, win._v3_dpr
    return (image_size[0] / 2 + (rx - foot_x) * ts,
            image_size[1] - (MARGIN_BOTTOM + win._height * V2_FOOT_GAP_RATIO) * dpr + (ry - foot_y) * ts)


def side_panel(side: str):
    """一格：渲染图（1:1 像素）、人物 alpha 外框、鼓起脸颊处的外轮廓 x 和脸颊 y。"""
    from shion.app import SnapshotScene

    with SnapshotScene("idle", height=260, activity="quiet", seed=SEED, scale=SCALE, side=side) as scene:
        scene.advance_to(.3)
        image = scene.render().copy()
        win = scene.win
        cheek = cheek_pixel(win, (image.width(), image.height()), side)
    image.setDevicePixelRatio(1)
    alpha = pil_image(image).getchannel("A")
    box = alpha.getbbox()
    if not (box[0] <= cheek[0] <= box[2] and box[1] <= cheek[1] <= box[3]):
        raise ValueError(f"脸颊点 {cheek} 不在人物外框 {box} 内")
    row = [x for x in range(alpha.width) if alpha.getpixel((x, round(cheek[1]))) > 0]
    edge = max(row) if side == "right" else min(row)
    return image, box, edge, cheek[1]


def side_image(lang: str):
    """靠屏幕左 / 右半边时脸鼓向另一侧：两个人物并排，下方标注位置，箭头从中间指向各自鼓起的脸颊。"""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    from shion.weekly_ui import card_font

    panels = [side_panel(side) for side, _ in SIDE_PANELS]
    width = panels[0][0].width()
    bottom = max(p[1][3] for p in panels)
    canvas = QImage(width * 2, bottom + 90 * SCALE, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(ARROW_COLOR), 5 * SCALE)
        pen.setCapStyle(Qt.RoundCap)
        for (side, slot), (image, box, edge, cheek_y), label in zip(SIDE_PANELS, panels, SIDE_LABELS[lang]):
            offset = slot * width
            painter.drawImage(offset, 0, image)
            # 箭头：尖端贴着鼓起一侧的外轮廓，尾巴伸向两个人物之间的空隙。
            direction = 1 if side == "right" else -1
            tip = QPointF(offset + edge + direction * 8 * SCALE, cheek_y)
            tail = QPointF(tip.x() + direction * 54 * SCALE, cheek_y)
            painter.setPen(pen)
            painter.drawLine(tail, tip)
            for dy in (-14 * SCALE, 14 * SCALE):
                painter.drawLine(tip, QPointF(tip.x() + direction * 18 * SCALE, cheek_y + dy))
            painter.setPen(QColor("#4A3B36"))
            painter.setFont(card_font(lang, 36, True))
            centre = offset + (box[0] + box[2]) / 2
            painter.drawText(QRectF(centre - 320 * SCALE, bottom + 14 * SCALE, 640 * SCALE, 56 * SCALE),
                             Qt.AlignHCenter | Qt.AlignTop, label)
    finally:
        painter.end()
    return canvas


def still_images():
    from shion.app import SnapshotScene, render_snapshot_panel

    yield "pat.png", pat_image()
    yield "pinch.png", gesture_image("pinch", .6)
    yield "lift.png", lift_image()
    yield "working.png", working_image()
    for lang in FONTS:
        yield f"side.{lang}.png", side_image(lang)
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


def weekly_images():
    """周报卡片只用 shion.weekly.preview 的合成数据。"""
    from shion.weekly import preview, title_for
    from shion.weekly_ui import render_card

    for lang in FONTS:
        data = preview(lang)
        data["totals"]["seven_day_peak"] = WEEKLY_SEVEN_DAY_PEAK
        data["title"] = title_for(data["totals"], lang)
        image = pil_image(render_card(data)).convert("RGB")
        yield f"weekly.{lang}.png", downsample(image, WEEKLY_SIZE)


def stamina_image(lang: str):
    """四档体力横排：同一裁切框保持脚底对齐，下方标注档位。"""
    from PySide6.QtCore import QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from shion.app import SnapshotScene
    from shion.weekly_ui import card_font

    sprites = []
    for state, _ in STAMINA_TIERS:
        with SnapshotScene(state, height=150, seed=SEED, scale=SCALE) as scene:
            scene.advance_to(.3)
            sprites.append(scene.render())
    boxes = [pil_image(image).getchannel("A").getbbox() for image in sprites]
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    column, label = 320, 110
    column = max(column, right - left + 24)
    canvas = QImage(column * len(sprites), bottom - top + label, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    try:
        for index, (image, (_, percent)) in enumerate(zip(sprites, STAMINA_TIERS)):
            piece = image.copy(QRect(left, top, right - left, bottom - top))
            piece.setDevicePixelRatio(1)  # 按像素拼接，避免 2x 截图被再缩一半
            x = index * column + (column - piece.width()) // 2
            painter.drawImage(x, 0, piece)
            area = QRectF(index * column, bottom - top + 8, column, 48)
            painter.setPen(QColor("#4A3B36"))
            painter.setFont(card_font(lang, 34, True))
            painter.drawText(area, Qt.AlignCenter, STAMINA_NAMES[lang][index])
            painter.setPen(QColor("#8A7A72"))
            painter.setFont(card_font(lang, 28))
            painter.drawText(area.translated(0, 50), Qt.AlignCenter, percent)
    finally:
        painter.end()
    return canvas


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
        limit = size_limit(name)
        if len(data) > limit:
            raise ValueError(f"{name} 超限：{len(data)} > {limit} 字节")
        with Image.open(path) as image:
            expected = image_size(name)
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
                if duration != GIF_DURATION_MS or image.convert("RGB").tobytes() != first:
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
    # 先生成、校验全部文件；编码或预算失败不改动已有成品。
    with tempfile.TemporaryDirectory(prefix=".make-media-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        write_gif(staging / "hero.gif", hero_frames())
        for name, image in still_images():
            downsample(card(image, STILL_SIZE), STILL_SIZE).save(staging / name, compress_level=9)
        for name, image in weekly_images():
            image.save(staging / name, compress_level=9)
        for lang in FONTS:
            downsample(card(stamina_image(lang), STAMINA_SIZE), STAMINA_SIZE).save(
                staging / f"stamina.{lang}.png", compress_level=9)
        report = validate_files(staging, other_bytes)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            (staging / name).replace(output_dir / name)
    del app
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "images",
                        help="输出目录（默认仓库 docs/images，仅替换本工具生成的文件）")
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
        target = args.output_dir / item["file"]
        try:
            path = os.path.relpath(target, ROOT).replace("\\", "/")
        except ValueError:  # Different drive: no relative path exists.
            path = str(target).replace("\\", "/")
        print(f"{path}: {item['width']}x{item['height']}, {item['bytes']} bytes, SHA-256 {item['sha256']}")
    print(f"generated total: {sum(item['bytes'] for item in report)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
