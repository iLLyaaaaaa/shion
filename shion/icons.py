"""源码与冻结程序共用的多尺寸窗口图标（只需要 Qt 内置 PNG 支持）。"""
from pathlib import Path

ICON_SIZES = (256, 64, 48, 32, 16)
ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icon"


def application_icon():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    icon = QIcon()
    for size in ICON_SIZES:
        name = "shion.png" if size == 256 else f"shion-{size}.png"
        icon.addFile(str(ICON_DIR / name), QSize(size, size))
    return icon
