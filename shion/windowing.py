"""窗口层级与面板定位；前移只调整 Z 序，不激活窗口。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication


def set_topmost(window, on: bool) -> None:
    """Qt 改 flags 会隐藏/重建 Windows 窗口，恢复原有几何、mask 和可见性。"""
    if bool(window.windowFlags() & Qt.WindowStaysOnTopHint) == on:
        return
    visible, geometry, mask = window.isVisible(), window.geometry(), window.mask()
    window.setWindowFlag(Qt.WindowStaysOnTopHint, on)
    window.setGeometry(geometry)
    window.setMask(mask)
    if visible:
        window.show()  # 所有受此开关控制的窗口均设置 WA_ShowWithoutActivating
        window.setGeometry(geometry)
        window.setMask(mask)


def raise_without_activation(window) -> None:
    if not window.isVisible():
        return
    if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        position = user32.SetWindowPos
        position.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
        position.restype = wintypes.BOOL
        # HWND_TOP：只前移一次，不改变 TOPMOST 属性。禁止 SetForegroundWindow/activateWindow。
        position(int(window.winId()), 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    else:
        window.raise_()


def place_dialog(body, size, avail, gap=8):
    """先右后左；两侧都不足时尝试上下，最后在屏内选重叠面积最小的位置。"""
    bx, by, bw, bh = body
    w, h = size
    ax, ay, aw, ah = avail
    clamp_x = lambda x: max(ax, min(x, ax + aw - w))
    clamp_y = lambda y: max(ay, min(y, ay + ah - h))
    cy = clamp_y(by + (bh - h) // 2)
    candidates = [(bx + bw + gap, cy), (bx - w - gap, cy),
                  (clamp_x(bx + (bw - w) // 2), by - h - gap),
                  (clamp_x(bx + (bw - w) // 2), by + bh + gap)]
    screen, pet = QRect(ax, ay, aw, ah), QRect(bx, by, bw, bh)
    for x, y in candidates:
        rect = QRect(x, y, w, h)
        if screen.contains(rect) and not rect.intersects(pet):
            return x, y
    candidates = [(clamp_x(x), clamp_y(y)) for x, y in candidates]
    def overlap(pos):
        rect = QRect(*pos, w, h).intersected(pet)
        return rect.width() * rect.height()
    return min(candidates, key=overlap)


def position_dialog(window, body) -> None:
    """使用身体所在显示器的可用区，包含原生对话框边框。"""
    screen = QGuiApplication.screenAt(QPoint(body[0] + body[2] // 2, body[1] + body[3] // 2))
    screen = screen or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    # 面板没有边框；QMessageBox 显示后才能取得真实边框尺寸。
    frame = window.frameGeometry()
    x, y = place_dialog(body, (frame.width(), frame.height()),
                        (g.x(), g.y(), g.width(), g.height()))
    window.move(x, y)
