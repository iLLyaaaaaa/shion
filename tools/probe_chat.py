"""Probe: which signals mark the start/end of a chat reply in Claude desktop.

Read-only: changes no Claude or system setting. Five methods run side by side
and append metadata-only events to build/probe-chat.jsonl:
  uia    UI Automation: does a "Stop" button exist (button name only)
  shell  RegisterShellHookWindow: flash / activate events of Claude windows
  toast  UserNotificationListener: app id + time of Claude toasts
  log    size changes + keyword hit counts of Claude log files (no line text)
  title  main window title length / changed flag + minimized/foreground state
Never recorded: conversation text, window title text, notification body,
log line text. Every emitted value is a bool, number or a short fixed label.

Usage:
  python tools/probe_chat.py                 # run; press keys to mark
  python tools/probe_chat.py --notify-auth   # also ask Windows for toast access
  python tools/probe_chat.py --report        # compare table from the jsonl
Keys: a=round "foreground"  b=round "minimized"  1=task sent  2=reply done
      q=quit
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import re
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "probe-chat.jsonl"
REPORT = ROOT / "build" / "probe-chat-report.md"
STOP_FILE = ROOT / "build" / "probe-chat.stop"

STOP_RE = re.compile(r"^(?:停止する|停止|Stop)(?:\W.{0,20}|生成.{0,10})?$", re.I)
UIA_DEPTH = 14
LOG_KEYWORDS = ("start", "complete", "stream", "finish", "stop")
LOG_EXT = (".log", ".jsonl", ".txt")
LOG_MAX_FILES = 40
LOG_READ_CAP = 1024 * 1024


class Probe:
    def __init__(self, out: Path):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.fh = open(out, "a", encoding="utf-8")
        self.stop = threading.Event()
        self.round = "none"
        self.hwnd = 0                      # main Claude window (0 = none)
        self.hwnds: set[int] = set()       # all Claude top-level windows
        self.pid_cache: dict[int, bool] = {}

    def emit(self, m: str, ev: str, **meta) -> None:
        rec = {"t": round(time.monotonic() - self.t0, 3),
               "wall": datetime.now().isoformat(timespec="milliseconds"),
               "m": m, "ev": ev, "round": self.round}
        for k, v in meta.items():
            # whitelist: scalars only, strings clipped (labels, never text)
            rec[k] = v[:60] if isinstance(v, str) else v
        with self.lock:
            self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.fh.flush()

    def is_claude_pid(self, pid: int) -> bool:
        if pid in self.pid_cache:
            return self.pid_cache[pid]
        ok = False
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                p = buf.value.lower()
                # desktop app only: not the Claude Code CLI that is also claude.exe
                ok = p.endswith("\\claude.exe") and "windowsapps" in p
            k32.CloseHandle(h)
        self.pid_cache[pid] = ok
        return ok

    def is_claude_hwnd(self, hwnd: int) -> bool:
        import win32process
        try:
            return self.is_claude_pid(win32process.GetWindowThreadProcessId(hwnd)[1])
        except Exception:
            return False


# --- 5. window title + window discovery ------------------------------------
def title_loop(p: Probe) -> None:
    import win32gui
    last_title_hash = None
    last_state = None
    while not p.stop.wait(0.5):
        found: list[int] = []

        def visit(h, _):
            if win32gui.IsWindowVisible(h) and p.is_claude_hwnd(h):
                found.append(h)
        try:
            win32gui.EnumWindows(visit, None)
        except Exception:
            pass
        p.hwnds = set(found)
        main = 0
        for h in found:
            try:
                if (win32gui.GetClassName(h) == "Chrome_WidgetWin_1"
                        and win32gui.GetWindowTextLength(h) > 0
                        and win32gui.GetWindow(h, 4) == 0):  # GW_OWNER
                    main = h
                    break
            except Exception:
                continue
        p.hwnd = main
        if not main:
            if last_state != "none":
                p.emit("title", "state", found=False, windows=len(found))
                last_state = "none"
            continue
        state = (win32gui.IsIconic(main) != 0, win32gui.GetForegroundWindow() == main)
        if state != last_state:
            p.emit("title", "state", found=True, minimized=state[0],
                   foreground=state[1], windows=len(found))
            last_state = state
        try:
            title = win32gui.GetWindowText(main)
        except Exception:
            continue
        th = hash(title)  # in memory only, never written
        if last_title_hash is not None and th != last_title_hash:
            p.emit("title", "changed", len=len(title))
        last_title_hash = th


# --- 1. UI Automation ---------------------------------------------------
def uia_loop(p: Probe) -> None:
    import uiautomation as auto
    import win32gui
    with auto.UIAutomationInitializerInThread():
        last = None
        empty = 0
        triggered = False
        scans = 0
        while not p.stop.wait(0.5):
            hwnd = p.hwnd
            if not hwnd:
                continue
            t = time.perf_counter()
            nodes = 0
            found = None
            try:
                root = auto.ControlFromHandle(hwnd)
                for c, _depth in auto.WalkControl(root, includeTop=False, maxDepth=UIA_DEPTH):
                    nodes += 1
                    if c.ControlTypeName == "ButtonControl":
                        name = c.Name or ""
                        if STOP_RE.match(name):
                            found = name
                            break
            except Exception as e:
                p.emit("uia", "err", kind=type(e).__name__)
                continue
            ms = int((time.perf_counter() - t) * 1000)
            scans += 1
            exists = found is not None
            if exists != last:
                p.emit("uia", "btn", exists=exists, name=found or "", nodes=nodes, ms=ms)
                last = exists
            if scans % 20 == 0:
                p.emit("uia", "hb", nodes=nodes, ms=ms)
            empty = empty + 1 if nodes <= 3 else 0
            if empty >= 6 and not triggered:
                # a side-effect-free nudge: ask the window for its MSAA client object
                triggered = True
                try:
                    win32gui.SendMessageTimeout(hwnd, 0x3D, 0, -4, 2, 500)  # WM_GETOBJECT
                    p.emit("uia", "tree_trigger", how="WM_GETOBJECT/OBJID_CLIENT")
                except Exception as e:
                    p.emit("uia", "tree_trigger", how="failed", kind=type(e).__name__)


# --- 2. shell hook -----------------------------------------------------------
def shell_loop(p: Probe) -> None:
    import win32api
    import win32con
    import win32gui
    shellhook = win32gui.RegisterWindowMessage("SHELLHOOK")
    names = {4: "activated", 0x8004: "activated", 0x8006: "flash"}

    def wndproc(hwnd, msg, wp, lp):
        if msg == shellhook and wp in names and p.is_claude_hwnd(lp):
            p.emit("shell", names[wp], main=(lp == p.hwnd), code=wp)
        elif msg == win32con.WM_TIMER and p.stop.is_set():
            win32gui.DestroyWindow(hwnd)
        elif msg == win32con.WM_DESTROY:
            try:
                ctypes.windll.user32.DeregisterShellHookWindow(hwnd)
            finally:
                win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wp, lp)

    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "ShionProbeShellHook"
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpfnWndProc = wndproc
    atom = win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(atom, "", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
    if not ctypes.windll.user32.RegisterShellHookWindow(hwnd):
        p.emit("shell", "unavailable", reason="register_failed")
        return
    ctypes.windll.user32.SetTimer(hwnd, 1, 500, None)
    p.emit("shell", "ready")
    win32gui.PumpMessages()


# --- 3. Windows notifications ----------------------------------------------
def toast_loop(p: Probe, allow_prompt: bool) -> None:
    asyncio.run(_toast_main(p, allow_prompt))


async def _toast_main(p: Probe, allow_prompt: bool) -> None:
    try:
        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener, UserNotificationListenerAccessStatus as AS)
        listener = UserNotificationListener.current
        status = listener.get_access_status()
        p.emit("toast", "access", status=status.name)
        if status == AS.UNSPECIFIED and allow_prompt:
            status = await listener.request_access_async()
            p.emit("toast", "access_after_prompt", status=status.name)
        if status != AS.ALLOWED:
            p.emit("toast", "unavailable", reason="not_allowed")
            return
        seen: set[int] = set()
        first = True
        while not p.stop.is_set():
            for n in await listener.get_notifications_async(NotificationKinds.TOAST):
                if n.id in seen:
                    continue
                seen.add(n.id)
                aumid = n.app_info.app_user_model_id or ""
                if "claude" in aumid.lower():
                    p.emit("toast", "toast", aumid=aumid, preexisting=first,
                           created=n.creation_time.isoformat(timespec="seconds"))
            first = False
            await asyncio.sleep(1)
    except Exception as e:
        p.emit("toast", "unavailable", reason=type(e).__name__)


# --- 4. log files --------------------------------------------------------
def _log_roots() -> list[Path]:
    roots = []
    appdata = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if appdata:
        roots.append(Path(appdata) / "Claude")
    if local:
        roots.append(Path(local) / "Claude")
        pk = Path(local) / "Packages"
        if pk.is_dir():
            roots.extend(pk.glob("Claude_*"))
    return roots


def _scan_logs() -> list[Path]:
    cutoff = time.time() - 7 * 86400
    files: list[Path] = []
    for root in _log_roots():
        if not root.is_dir():
            continue
        for dirpath, dirs, names in os.walk(root):
            if Path(dirpath).relative_to(root).parts.__len__() >= 4:
                dirs[:] = []
            for n in names:
                if n.lower().endswith(LOG_EXT):
                    f = Path(dirpath) / n
                    try:
                        if f.stat().st_mtime >= cutoff:
                            files.append(f)
                    except OSError:
                        pass
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:LOG_MAX_FILES]


def _label(path: Path) -> str:
    """Path with the user part masked, so the jsonl holds no user name."""
    s = str(path)
    for var in ("APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(var)
        if v and s.lower().startswith(v.lower()):
            return f"%{var}%" + s[len(v):]
    return "<other>\\" + path.name


def log_loop(p: Probe) -> None:
    kw = [k.encode() for k in LOG_KEYWORDS]
    state: dict[Path, int] = {}
    tick = 0
    while not p.stop.is_set():
        if tick % 30 == 0:
            files = _scan_logs()
            for f in files:
                if f not in state:
                    try:
                        state[f] = f.stat().st_size
                    except OSError:
                        continue
                    p.emit("log", "discovered", file=_label(f), size=state[f])
            if tick == 0 and not files:
                p.emit("log", "log_dir_not_found")
        for f in list(state):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            old = state[f]
            if size == old:
                continue
            counts = {k.decode(): 0 for k in kw}
            if size > old:
                try:
                    with open(f, "rb") as fh:
                        fh.seek(old)
                        data = fh.read(min(size - old, LOG_READ_CAP)).lower()
                    for k in kw:
                        counts[k.decode()] = data.count(k)
                except OSError:
                    pass
            p.emit("log", "grow" if size > old else "shrink", file=_label(f),
                   delta=size - old, **counts)
            state[f] = size
        tick += 1
        p.stop.wait(1.0)


# --- runner ----------------------------------------------------------------
def run(args) -> None:
    p = Probe(OUT)
    loops = {
        "title": (title_loop, (p,)),
        "uia": (uia_loop, (p,)),
        "shell": (shell_loop, (p,)),
        "toast": (toast_loop, (p, args.notify_auth)),
        "log": (log_loop, (p,)),
    }
    chosen = args.only or list(loops)
    threads = [threading.Thread(target=loops[m][0], args=loops[m][1], daemon=True)
               for m in chosen]
    STOP_FILE.unlink(missing_ok=True)
    p.emit("probe", "start", methods=",".join(chosen))
    for t in threads:
        t.start()
    time.sleep(2)
    print(f"写入 {OUT}  方法: {','.join(chosen)}")
    if not args.only:
        print(f"Claude 桌面版窗口: {len(p.hwnds)} 个, 主窗口: {'找到' if p.hwnd else '未找到'}")
    print("按键: a=前台轮  b=最小化轮  1=任务已发出  2=回复已结束  q=退出")
    import msvcrt
    started = time.monotonic()
    while not p.stop.is_set():
        if args.duration and time.monotonic() - started > args.duration:
            break
        if STOP_FILE.exists():  # lets a background run be stopped cleanly
            break
        if msvcrt.kbhit():
            ch = msvcrt.getwch().lower()
            if ch == "a":
                p.round = "foreground"
                p.emit("mark", "round", name="foreground")
            elif ch == "b":
                p.round = "minimized"
                p.emit("mark", "round", name="minimized")
            elif ch in "12":
                p.emit("mark", "start" if ch == "1" else "end")
            elif ch == "q":
                break
            else:
                continue
            print(f"[{time.monotonic() - p.t0:7.1f}s] {ch} (round={p.round})")
        time.sleep(0.05)
    p.emit("probe", "stop")
    p.stop.set()
    for t in threads:
        t.join(timeout=3)


# --- report ----------------------------------------------------------------
# which events count as a signal per method
def _is_signal(r: dict) -> bool:
    m, ev = r["m"], r["ev"]
    if m == "uia":
        return ev == "btn"
    if m == "shell":
        # "activated" also fires when the user alt-tabs to the window, so it
        # is not a chat signal; only a taskbar flash is
        return ev == "flash"
    if m == "toast":
        return ev == "toast" and not r.get("preexisting")
    if m == "log":
        return ev == "grow" and sum(r.get(k, 0) for k in LOG_KEYWORDS) > 0
    if m == "title":
        return ev == "changed"
    return False


NOTES = {  # my expectations, to be checked against the measured columns
    "uia": ("无(只读 UIA)", "高:依赖按钮文案/无障碍树结构,界面改版即失效"),
    "shell": ("无", "中:依赖 Claude 在完成时闪烁任务栏,行为可能被改"),
    "toast": ("需要(通知访问授权)", "中:依赖 Claude 发系统通知及其设置"),
    "log": ("无", "高:日志位置/格式/关键词随版本变,MSIX 可能虚拟化路径"),
    "title": ("无", "高:标题是否随状态变化取决于 UI 实现"),
}


def report() -> None:
    recs = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line]
    rounds: dict[str, dict] = {}
    for r in recs:
        if r["m"] == "mark" and r["ev"] in ("start", "end"):
            rounds.setdefault(r["round"], {})[r["ev"]] = r["t"]
    lines = ["# probe-chat 对比", "",
             "延迟 = 信号时间 − 手动打标时间(含你按键的 1~2 秒误差)。"
             "误报 = 不在任一标记附近(开始前 2s~后 10s,结束前 5s~后 15s)的信号数。", ""]
    for name, mk in rounds.items():
        if "start" not in mk or "end" not in mk:
            lines += [f"## 轮次 {name}: 缺少 1/2 标记,跳过", ""]
            continue
        t1, t2 = mk["start"], mk["end"]
        lines += [f"## 轮次 {name}(任务时长 {t2 - t1:.0f}s)", "",
                  "| 方法 | 抓到开始 | 开始延迟 | 抓到结束 | 结束延迟 | 误报 | 授权 | 更新失效风险 |",
                  "|---|---|---|---|---|---|---|---|"]
        for m in ("uia", "shell", "toast", "log", "title"):
            sig = [r for r in recs if r["m"] == m and r["round"] == name and _is_signal(r)]
            if m == "uia":
                starts = [r for r in sig if r["exists"] and r["t"] >= t1 - 2]
                s = starts[0]["t"] if starts else None
                ends = [r for r in sig if not r["exists"] and s is not None and r["t"] > s]
                e = ends[0]["t"] if ends else None
            else:
                s = next((r["t"] for r in sig if t1 - 2 <= r["t"] <= t1 + 10), None)
                e = next((r["t"] for r in sig if t2 - 5 <= r["t"] <= t2 + 15), None)
            near = [r for r in sig if (t1 - 2 <= r["t"] <= t1 + 10) or (t2 - 5 <= r["t"] <= t2 + 15)]
            fp = len(sig) - len(near)
            if m == "log":
                fp = "n/a(流式期间持续写入)" if sig else 0
            fmt = lambda x, ref: "-" if x is None else f"{x - ref:+.1f}s"
            auth, risk = NOTES[m]
            unavailable = any(r["m"] == m and r["ev"] in ("unavailable", "log_dir_not_found") for r in recs)
            if unavailable and not sig:
                lines.append(f"| {m} | 不可用 | - | 不可用 | - | - | {auth} | {risk} |")
            else:
                lines.append(f"| {m} | {'是' if s is not None else '否'} | {fmt(s, t1)} | "
                             f"{'是' if e is not None else '否'} | {fmt(e, t2)} | {fp} | {auth} | {risk} |")
        lines.append("")
    lines += ["授权/风险两列是实现前的预期,不是测量值;其余列来自本次数据。"]
    text = "\n".join(lines)
    REPORT.write_text(text, encoding="utf-8")
    print(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true", help="print comparison from the jsonl")
    ap.add_argument("--notify-auth", action="store_true",
                    help="allow the OS toast-access prompt (otherwise only query status)")
    ap.add_argument("--duration", type=int, default=0, help="auto-quit after N seconds")
    ap.add_argument("--only", nargs="+", choices=("uia", "shell", "toast", "log", "title"),
                    help="run only these methods")
    args = ap.parse_args()
    if args.report:
        report()
    else:
        run(args)


if __name__ == "__main__":
    sys.exit(main())
