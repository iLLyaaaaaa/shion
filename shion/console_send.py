"""终端版 CC 这一轮结束后，替用户在它的输入框里发一句“继续”（不 import Qt）。

做法见 docs/experiments/send-continue.md：AttachConsole(CC 的 pid) → 读屏 → 确认输入行是空的、
屏幕上不像确认对话框 → WriteConsoleInputW 逐字写 + 回车 → FreeConsole。不切前台窗口、不模拟键盘。

只在单独的子进程里运行（附着期间本进程和 CC 共用控制台），诗音用 QProcess 调用：
    python -m shion.console_send --pid P --created C --text 继续
输出一行 JSON：{"ok": true} 或 {"ok": false, "reason": "gone|no_input|draft|dialog|error"}。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Optional

from shion import winproc

# 出现这些字样时不发送：回车会替用户点确认对话框里的默认项。对话内容里碰巧有也拒绝（故意保守）
DANGER_WORDS = ("Do you want", "Yes", "No,", "Allow", "allow", "trust", "Trust", "允许", "信任",
                "Enter to confirm", "Esc to cancel", "Enter to select", "proceed?")
# 确认框的编号选项总有一个带选中标记（❯ 1. Yes）；回复里的普通编号列表没有标记，不算
NUMBERED = re.compile(r"^\s*[│|]?\s*[>❯›]\s*\d+\.\s")
PROMPT_CHARS = (">", "❯")
# 空输入框里 CC 显示的灰色占位提示（例如 Try "write a test for <filepath>"）。读屏分不出颜色，
# 所以还要求光标正好停在提示符后面：用户打过字，光标会跟在字后面
PLACEHOLDER = re.compile(r'^Try ".*("|…)$')
BOX_EDGE = "│|"
SCAN_LINES = 25  # 只看屏幕最下面这么多行
INPUT_SEARCH = 15  # 输入框应该在最下面这么多行里


def _is_rule(line: str) -> bool:
    s = line.strip()
    return len(s) >= 10 and s.count("─") >= len(s) * 0.8


def _inner(line: str) -> str:
    """去掉边框竖线和空白。"""
    return line.strip().strip(BOX_EDGE).strip()


def check_screen(lines: list[str], cursor: Optional[tuple[int, int]] = None) -> Optional[str]:
    """屏幕（从上到下的行）能不能安全地写入“继续”+回车：能返回 None，否则返回原因。

    cursor：控制台光标 (列, 行)，行号和 lines 的下标一致；None 表示不知道。
    - dialog：最下面一段像确认对话框（有确认字样或编号选项）；
    - no_input：找不到“两条横线夹住、以 > / ❯ 开头”的输入行；
    - draft：输入行里有字（占位提示且光标在提示符后面除外），或输入有多行。
    """
    lines = [l.rstrip() for l in lines]
    offset = max(0, len(lines) - SCAN_LINES)
    tail = lines[offset:]
    for line in tail:
        if any(w in line for w in DANGER_WORDS) or NUMBERED.match(line):
            return "dialog"
    start = max(0, len(tail) - INPUT_SEARCH)
    for i in range(len(tail) - 1, start, -1):
        text = _inner(tail[i])
        if not text.startswith(PROMPT_CHARS) or not _is_rule(tail[i - 1]):
            continue
        rest = text[1:].strip()
        if rest:
            col = len(tail[i]) - len(tail[i].lstrip()) + 2  # 提示符后面一格空格之后
            if not (PLACEHOLDER.match(rest) and cursor == (col, i + offset)):
                return "draft"
        if i + 1 >= len(tail) or not _is_rule(tail[i + 1]):
            return "draft"  # 下一行不是横线：输入不止一行
        return None
    return "no_input"


def check_process(pid: int, created: int, table: Optional[dict] = None, created_fn=winproc.process_created) -> bool:
    """还是 hook 报上来的那个 CC：进程在、名字是 claude.exe、创建时间对得上（防 PID 复用）。"""
    table = winproc.process_table() if table is None else table
    entry = table.get(pid)
    return bool(entry) and entry[1].lower() == "claude.exe" and created_fn(pid) == created


# ---------------------------------------------------------------- 控制台（只在 Windows 子进程里用）
def _console():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                    ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                    ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]

    class _EVENT(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                    ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]

    class CSBI(ctypes.Structure):
        _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                    ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]

    return ctypes, wintypes, k32, INPUT_RECORD, COORD, CSBI


def _send_attached(text: str, pace: float) -> dict:
    ctypes, wintypes, k32, INPUT_RECORD, COORD, CSBI = _console()
    invalid = wintypes.HANDLE(-1).value

    def open_con(name):
        h = k32.CreateFileW(name, 0xC0000000, 0x3, None, 3, 0, None)  # 读写、共享读写、OPEN_EXISTING
        if not h or h == invalid:
            raise OSError(f"打不开 {name}: {ctypes.get_last_error()}")
        return h

    def read_screen(hout):
        info = CSBI()
        if not k32.GetConsoleScreenBufferInfo(wintypes.HANDLE(hout), ctypes.byref(info)):
            raise OSError(f"GetConsoleScreenBufferInfo 失败: {ctypes.get_last_error()}")
        width, w = info.dwSize.X, info.srWindow
        out = []
        for y in range(w.Top, w.Bottom + 1):
            buf = ctypes.create_unicode_buffer(width)
            n = wintypes.DWORD()
            k32.ReadConsoleOutputCharacterW(wintypes.HANDLE(hout), buf, width, COORD(0, y), ctypes.byref(n))
            out.append(buf.value[: n.value].rstrip())
        return out

    def key(ch, vk, down, scan=0):
        rec = INPUT_RECORD()
        rec.EventType = 0x0001  # KEY_EVENT
        ev = rec.Event.KeyEvent
        ev.bKeyDown, ev.wRepeatCount, ev.wVirtualKeyCode, ev.wVirtualScanCode, ev.uChar = down, 1, vk, scan, ch
        return rec

    def write(hin, recs):
        arr = (INPUT_RECORD * len(recs))(*recs)
        n = wintypes.DWORD()
        if not k32.WriteConsoleInputW(wintypes.HANDLE(hin), arr, len(recs), ctypes.byref(n)):
            raise OSError(f"WriteConsoleInputW 失败: {ctypes.get_last_error()}")

    hin, hout = open_con("CONIN$"), open_con("CONOUT$")
    try:
        info = CSBI()
        k32.GetConsoleScreenBufferInfo(wintypes.HANDLE(hout), ctypes.byref(info))
        cursor = (info.dwCursorPosition.X, info.dwCursorPosition.Y - info.srWindow.Top)
        reason = check_screen(read_screen(hout), cursor)
        if reason:
            return {"ok": False, "reason": reason}
        for ch in text:  # VK_PACKET：直接带字符，不依赖键盘布局
            write(hin, [key(ch, 0xE7, True), key(ch, 0xE7, False)])
            time.sleep(pace)
        time.sleep(pace * 5)
        write(hin, [key("\r", 0x0D, True, 0x1C), key("\r", 0x0D, False, 0x1C)])
        return {"ok": True}
    finally:
        k32.CloseHandle(wintypes.HANDLE(hin))
        k32.CloseHandle(wintypes.HANDLE(hout))


def send(pid: int, created: int, text: str, pace: float = 0.03) -> dict:
    if os.name != "nt":
        return {"ok": False, "reason": "error"}
    if not text or not check_process(pid, created):
        return {"ok": False, "reason": "gone"}
    _, _, k32, *_ = _console()
    k32.SetConsoleCtrlHandler(None, True)  # 附着期间别被对方的 Ctrl+C 带走
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        return {"ok": False, "reason": "gone"}
    try:
        return _send_attached(text, pace)
    except OSError:
        return {"ok": False, "reason": "error"}
    finally:
        k32.FreeConsole()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--created", type=int, required=True)
    ap.add_argument("--text", required=True)
    args = ap.parse_args(argv)
    try:
        result = send(args.pid, args.created, args.text)
    except Exception:
        result = {"ok": False, "reason": "error"}
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
