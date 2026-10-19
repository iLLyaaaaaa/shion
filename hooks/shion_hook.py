"""Claude Code hook 脚本：把事件转发给本机的 Shion 桌宠。

只用标准库。无论发生什么都返回 0、不输出多余内容，绝不能影响 Claude Code。
用法：shion_hook.py <SessionStart|UserPromptSubmit|PreToolUse|Stop|Notification>
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
    "PostToolUseFailure": "tool_error",
    "Stop": "stop",
    "Notification": "notification",
}
ROOT = Path(__file__).resolve().parent.parent


def base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('SHION_PORT') or 47613}"


def request(path: str, payload=None):
    """成功返回解析后的 JSON，失败返回 None。"""
    try:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base_url() + path, data=data)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机请求不走系统代理
        with opener.open(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def inject_praise_enabled() -> bool:
    return read_save().get("inject_praise", True) is not False


def read_save() -> dict:
    try:
        directory = os.environ.get("SHION_DATA_DIR")
        path = (Path(directory) if directory else Path(os.environ["APPDATA"]) / "Shion") / "state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def praise_line() -> str:
    """只用标准库读三语 UI 文本，不加载 Qt。"""
    lang = read_save().get("language")
    lang = lang if lang in ("zh", "en", "ja") else "zh"
    try:
        raw = json.loads((ROOT / "assets" / "lines" / f"{lang}.json").read_text(encoding="utf-8"))
        return raw["ui"]["hook_praise"]
    except Exception:
        return "[诗音] 用户觉得你刚才做得很好。"


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
    etype = EVENTS.get(name)
    if etype is None:
        return
    if name == "PostToolUseFailure" and data.get("is_interrupt"):
        return
    if name == "SessionStart":
        ensure_running()
    detail = build_detail(name, data)
    request("/event", {"type": etype} if detail is None else {"type": etype, "detail": detail[:MAX_DETAIL]})
    if name == "UserPromptSubmit":
        result = request("/praise/take", {})
        count = result.get("count", 0) if isinstance(result, dict) else 0
        if isinstance(count, int) and count > 0 and inject_praise_enabled():
            line = praise_line() + "\n"
            sys.stdout.buffer.write(line.encode("utf-8"))
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
    worker.join(12 if sys.argv[1:2] == ["SessionStart"] else 2.5)
    try:
        sys.stdout.flush()
    except BaseException:
        pass
    os._exit(0)
