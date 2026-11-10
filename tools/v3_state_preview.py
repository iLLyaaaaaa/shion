"""S6 验收用：开一个 V3 诗音窗口 + 一个按钮面板，切换全部状态（含菜单里没有的 neglect1/yawn/slump/collapse）。

python -m tools.v3_state_preview [--height 260] [--auto 8]

不连 Claude、不读写存档、不开端口。诗音窗口里照常可以捏脸、摸头、敲头、挠痒、拎脸颊。
面板：点状态名切换（带 V2 的切换过渡）；“喂零食”= 点头咀嚼 2 秒；关掉面板即退出。
--auto N：每 N 秒自动切到下一个状态。
"""
from __future__ import annotations

import argparse
import sys

STATES = ["idle", "working", "neglect1", "neglect2", "yawn", "slump", "collapse",
          "sleep", "desk", "bed", "dizzy", "stop", "happy", "proud", "done", "cheer"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--height", type=int, choices=[160, 200, 260, 320], default=260)
    p.add_argument("--auto", type=float, default=0, help="每 N 秒自动切换（0 = 只用按钮）")
    a = p.parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QGridLayout, QPushButton, QWidget
    app = QApplication.instance() or QApplication(sys.argv)
    from shion.v3_window import V3PetWindow

    win = V3PetWindow(height=a.height, debug=False)
    win.auto_side = False
    panel = QWidget()
    panel.setWindowTitle("V3 状态预览")
    grid = QGridLayout(panel)
    buttons = {}
    index = [0]

    def show(i):
        index[0] = i % len(STATES)
        name = STATES[index[0]]
        win.set_state(name, animate=True)
        for n, b in buttons.items():
            b.setStyleSheet("font-weight: bold; background: #ffd9b3;" if n == name else "")

    for i, name in enumerate(STATES):
        b = QPushButton(name)
        b.clicked.connect(lambda _=False, i=i: show(i))
        grid.addWidget(b, i // 4, i % 4)
        buttons[name] = b
    chew = QPushButton("喂零食（点头咀嚼 2 秒）")
    chew.clicked.connect(lambda: win.start_chewing(2.0))
    grid.addWidget(chew, len(STATES) // 4 + 1, 0, 1, 4)

    avail = QGuiApplication.primaryScreen().availableGeometry()
    win.move(avail.center().x() - win.width() // 2, avail.bottom() - win.height())
    show(0)
    win.show()
    panel.show()
    panel.move(win.x() - panel.width() - 20, avail.bottom() - panel.height() - 40)
    app.setQuitOnLastWindowClosed(False)
    panel.destroyed.connect(app.quit)
    original_close = panel.closeEvent

    def close(e):
        original_close(e)
        win.close()
        app.quit()
    panel.closeEvent = close
    if a.auto > 0:
        timer = QTimer(panel)
        timer.timeout.connect(lambda: show(index[0] + 1))
        timer.start(int(a.auto * 1000))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
