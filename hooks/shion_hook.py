"""Claude Code hook 脚本：把事件转发给本机的 Shion 桌宠。

只用标准库。无论发生什么都返回 0、不输出多余内容，绝不能影响 Claude Code。
用法：shion_hook.py <SessionStart|UserPromptSubmit|PreToolUse|PostToolUse|PostToolUseFailure|Stop|Notification>

暂停/继续：PreToolUse 在用户点了“暂停”时一直等；诗音没开、连不上、出错一律放行。
反馈队列：PostToolUse（工作中）和 UserPromptSubmit（空闲时）把诗音里攒的反馈作为附加上下文送出。
"""
import json
import os
import subprocess
import sys
import threading
import re
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

TIMEOUT = 0.5
EVENTS = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "working",
    "PostToolUse": None,
    "PostToolUseFailure": "tool_error",
    "Stop": "stop",
    "Notification": "notification",
}
ROOT = Path(__file__).resolve().parent.parent


def base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('SHION_PORT') or 47613}"


def request(path: str, payload=None, timeout: float = TIMEOUT):
    """成功返回解析后的 JSON，失败返回 None。"""
    try:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base_url() + path, data=data)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机请求不走系统代理
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def read_save() -> dict:
    try:
        directory = os.environ.get("SHION_DATA_DIR")
        path = (Path(directory) if directory else Path(os.environ["APPDATA"]) / "Shion") / "state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def remote_setting(name: str, default: int, low: int, high: int) -> int:
    value = (read_save().get("remote") or {}).get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(value, high))


PAUSE_POLL = 25.0  # 每次长轮询最多等多久（服务端上限 30 秒）
PAUSE_REASON = "用户暂停了工作，请停下并等待用户指示"


def pause_limit() -> int:
    return remote_setting("pause_timeout", 1800, 60, 1880)


def pause_gate(limit: float, poll: float = PAUSE_POLL):
    """暂停期间一直等。返回 None = 放行；返回字符串 = 超时，要拒绝这次工具调用（理由）。

    诗音没开、请求失败、返回内容不对，都按“没暂停”处理，绝不把 CC 卡住。
    """
    result = request("/pause/wait", {"wait": 0})
    if not isinstance(result, dict) or result.get("paused") is not True:
        return None
    deadline = time.monotonic() + limit
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            request("/event", {"type": "pause_timeout"})
            return PAUSE_REASON
        wait = min(poll, remaining)
        result = request("/pause/wait", {"wait": wait}, timeout=wait + 3)
        if not isinstance(result, dict) or result.get("paused") is not True:
            return None


def emit(obj) -> None:
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def take_feedback() -> str:
    result = request("/feedback/take", {})
    text = result.get("text") if isinstance(result, dict) else ""
    return text if isinstance(text, str) else ""


def launch_shion() -> None:
    exe = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not exe.exists():
        return
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):  # CREATE_BREAKAWAY_FROM_JOB；被拒绝就去掉重试
        try:
            subprocess.Popen(
                [str(exe), "-m", "shion"], cwd=str(ROOT), creationflags=flags | extra,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "SHION_LAUNCHED_BY_HOOK": "1"},
            )
            return
        except OSError:
            continue


def ensure_running() -> None:
    if request("/health"):
        return
    launch_shion()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if request("/health"):
            return


MAX_DETAIL = 1000
TOOL_KIND = {
    "Read": "read", "NotebookRead": "read",
    "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit",
    "Write": "write",
    "Bash": "bash", "PowerShell": "bash",
    "Grep": "search", "Glob": "search",
    "WebFetch": "web", "WebSearch": "web",
    "Agent": "agent", "Task": "agent",
}


def _short(text, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_tool(tool_name, tool_input) -> dict:
    """把工具调用概括成 {"tool": 类别, "target": 简短目标}。不包含命令内容，文件只取文件名。"""
    kind = TOOL_KIND.get(tool_name, "other")
    ti = tool_input if isinstance(tool_input, dict) else {}
    target = ""
    if kind in ("read", "edit", "write"):
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        target = _short(re.split(r"[\\/]", str(path))[-1], 60) if path else ""
    elif kind == "search":
        target = _short(ti.get("pattern") or "", 20)
    elif kind == "web":
        target = _short(urlparse(str(ti.get("url") or "")).hostname or ti.get("query") or "", 60)
    elif kind == "agent":
        target = _short(ti.get("description") or "", 20)
    return {"tool": kind, "target": target}


def first_sentence(text, limit: int = 40) -> str:
    """取回复的第一句：去掉 markdown 符号，按句号/换行切，过长截断。"""
    if not isinstance(text, str):
        return ""
    for line in text.splitlines():
        line = re.sub(r"[#*>`]+", "", line).strip(" -\t")
        if not line:
            continue
        m = re.search(r"[。！？!?]|\.(?=\s|$)", line)
        sentence = line[: m.start()] if m else line
        return _short(sentence.strip(), limit)
    return ""


def read_input() -> dict:
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_detail(name: str, data: dict):
    """各事件发给桌宠的 detail（字符串或 None）。"""
    if name == "PreToolUse":
        return json.dumps(describe_tool(data.get("tool_name"), data.get("tool_input")), ensure_ascii=False)
    if name == "Stop":
        return first_sentence(data.get("last_assistant_message")) or None
    if name == "PostToolUseFailure":
        return _short(data.get("tool_name") or "", 40) or None
    return None


def main() -> None:
    data = read_input()
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in EVENTS:
        return
    etype = EVENTS[name]
    if name == "PostToolUseFailure" and data.get("is_interrupt"):
        return
    if name == "SessionStart":
        ensure_running()
    if name == "PostToolUse":
        text = take_feedback()
        if text:
            emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}})
        return
    if name == "PreToolUse":
        reason = pause_gate(pause_limit())
        if reason is not None:
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }})
            return
    detail = build_detail(name, data)
    request("/event", {"type": etype} if detail is None else {"type": etype, "detail": detail[:MAX_DETAIL]})
    if name == "UserPromptSubmit":
        text = take_feedback()
        if text:
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))
            sys.stdout.buffer.flush()


def _guarded_main() -> None:
    try:
        main()
    except BaseException:
        pass


if __name__ == "__main__":
    # 总时限：服务器卡住（收了连接不回包）时 socket 超时只管单次操作，这里兜底强制退出
    worker = threading.Thread(target=_guarded_main, daemon=True)
    worker.start()
    event = sys.argv[1:2]
    # PreToolUse 可能要等用户点“继续”，总时限 = 暂停上限 + 余量；其余事件很快
    worker.join(12 if event == ["SessionStart"] else (pause_limit() + 30 if event == ["PreToolUse"] else 2.5))
    try:
        sys.stdout.flush()
    except BaseException:
        pass
    os._exit(0)
