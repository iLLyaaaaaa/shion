"""实验：AttachConsole + WriteConsoleInputW，向终端里的 Claude Code 发送一条用户消息。

不切前台窗口、不用 SendInput。只是可行性实验，诗音正式代码不 import 它。

用法（PowerShell）：
    .venv\\Scripts\\python tools\\experiments\\console_send.py --list
    .venv\\Scripts\\python tools\\experiments\\console_send.py --pid 1234 --dry-run
    .venv\\Scripts\\python tools\\experiments\\console_send.py --pid 1234 --text 继续 --mode paced

--dry-run 只读屏幕不写入；屏幕上像是信任/权限确认对话框时一律中止（回车会选中默认项）。
屏幕内容和结果写进 --log 指定的文件，避免刷屏。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
u32.GetForegroundWindow.restype = wintypes.HWND

KEY_EVENT = 0x0001
VK_RETURN = 0x0D
VK_PACKET = 0xE7
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 0x1, 0x2
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value

# 出现这些字样时不发送：回车会替用户点“同意”
DANGER = ("trust", "Do you want", "Yes, proceed", "No, exit", "Allow", "允许", "信任", "❯ 1.", "> 1.")


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


class ENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def process_table() -> dict[int, tuple[int, str]]:
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    table = {}
    entry = ENTRY()
    entry.dwSize = ctypes.sizeof(ENTRY)
    ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
    while ok:
        table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
        ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
    k32.CloseHandle(wintypes.HANDLE(snap))
    return table


def list_cli() -> list[dict]:
    """终端版 CC：名叫 claude.exe、父进程不是 Claude 桌面端的进程。"""
    table = process_table()
    found = []
    for pid, (ppid, exe) in table.items():
        if exe.lower() != "claude.exe":
            continue
        parent = table.get(ppid, (0, ""))[1]
        if parent.lower() == "claude.exe":
            continue  # 桌面端自己或它管理的 CC 子进程（没有可写的用户控制台）
        found.append({"pid": pid, "parent": f"{parent}({ppid})"})
    return found


def key(ch: str, vk: int, down: bool, scan: int = 0) -> INPUT_RECORD:
    rec = INPUT_RECORD()
    rec.EventType = KEY_EVENT
    ev = rec.Event.KeyEvent
    ev.bKeyDown = down
    ev.wRepeatCount = 1
    ev.wVirtualKeyCode = vk
    ev.wVirtualScanCode = scan
    ev.uChar = ch
    return rec


def open_con(name: str) -> int:
    h = k32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE:
        raise OSError(f"打不开 {name}: {ctypes.get_last_error()}")
    return h


def read_screen(hout: int) -> list[str]:
    info = CSBI()
    if not k32.GetConsoleScreenBufferInfo(wintypes.HANDLE(hout), ctypes.byref(info)):
        raise OSError(f"GetConsoleScreenBufferInfo 失败: {ctypes.get_last_error()}")
    w = info.srWindow
    width = info.dwSize.X
    lines = []
    for y in range(w.Top, w.Bottom + 1):
        buf = ctypes.create_unicode_buffer(width)
        n = wintypes.DWORD()
        k32.ReadConsoleOutputCharacterW(wintypes.HANDLE(hout), buf, width, COORD(0, y), ctypes.byref(n))
        lines.append(buf.value[: n.value].rstrip())
    return lines


def write_records(hin: int, recs: list[INPUT_RECORD]) -> int:
    arr = (INPUT_RECORD * len(recs))(*recs)
    n = wintypes.DWORD()
    if not k32.WriteConsoleInputW(wintypes.HANDLE(hin), arr, len(recs), ctypes.byref(n)):
        raise OSError(f"WriteConsoleInputW 失败: {ctypes.get_last_error()}")
    return n.value


def send(pid: int, text: str, mode: str, dry_run: bool, wait: float, no_enter: bool = False) -> dict:
    result: dict = {"pid": pid, "text": text, "mode": mode, "dry_run": dry_run}
    fg_before = u32.GetForegroundWindow()
    k32.SetConsoleCtrlHandler(None, True)  # 附着期间别被对方的 Ctrl+C 带走
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        result["error"] = f"AttachConsole 失败: {ctypes.get_last_error()}"
        return result
    try:
        hin, hout = open_con("CONIN$"), open_con("CONOUT$")
        before = read_screen(hout)
        result["screen_before"] = before
        if mode == "esc":  # 只发 Esc：在确认对话框里等于“取消/拒绝”，不需要安全检查
            if not dry_run:
                result["written"] = write_records(hin, [key("\x1b", 0x1B, True, 0x01), key("\x1b", 0x1B, False, 0x01)])
                time.sleep(wait)
                result["screen_after"] = read_screen(hout)
            return result
        hits = [d for d in DANGER if any(d in line for line in before[-25:])]
        if hits:
            result["error"] = f"屏幕上像是确认对话框，中止：{hits}"
            return result
        if not dry_run:
            chars = []
            for ch in text:
                chars += [key(ch, VK_PACKET, True), key(ch, VK_PACKET, False)]
            enter = [] if no_enter else [key("\r", VK_RETURN, True, 0x1C), key("\r", VK_RETURN, False, 0x1C)]
            if mode == "burst":
                result["written"] = write_records(hin, chars + enter)
            else:
                written = 0
                for i in range(0, len(chars), 2):
                    written += write_records(hin, chars[i:i + 2])
                    time.sleep(0.03)
                time.sleep(0.15)
                if enter:
                    written += write_records(hin, enter)
                result["written"] = written
            time.sleep(wait)
            result["screen_after"] = read_screen(hout)
        k32.CloseHandle(wintypes.HANDLE(hin))
        k32.CloseHandle(wintypes.HANDLE(hout))
    finally:
        k32.FreeConsole()
        fg_after = u32.GetForegroundWindow()
        result["foreground_before"] = fg_before or 0
        result["foreground_after"] = fg_after or 0
        result["foreground_unchanged"] = fg_before == fg_after
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--text", default="继续")
    ap.add_argument("--mode", choices=("paced", "burst", "esc"), default="paced")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-enter", action="store_true", help="只写字不回车（模拟用户没发出的草稿）")
    ap.add_argument("--wait", type=float, default=1.5, help="写完后等几秒再读屏")
    ap.add_argument("--log", type=Path, help="结果 JSON 写到这里（默认只打印摘要）")
    args = ap.parse_args()
    if args.list:
        print(json.dumps(list_cli(), ensure_ascii=False, indent=1))
        return 0
    if not args.pid:
        ap.error("需要 --pid 或 --list")
    result = send(args.pid, args.text, args.mode, args.dry_run, args.wait, args.no_enter)
    if args.log:
        args.log.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {k: v for k, v in result.items() if not k.startswith("screen")}
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
