"""Claude Code hook 脚本：把事件转发给本机的 Shion 桌宠。

只用标准库。无论发生什么都返回 0、不输出多余内容，绝不能影响 Claude Code。
用法：shion_hook.py <SessionStart|UserPromptSubmit|PreToolUse|Stop|Notification>
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

TIMEOUT = 0.5
EVENTS = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "working",
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
    try:
        directory = os.environ.get("SHION_DATA_DIR")
        path = (Path(directory) if directory else Path(os.environ["APPDATA"]) / "Shion") / "state.json"
        return json.loads(path.read_text(encoding="utf-8")).get("inject_praise", True) is not False
    except Exception:
        return True


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


def main() -> None:
    try:
        sys.stdin.buffer.read()
    except Exception:
        pass
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    etype = EVENTS.get(name)
    if etype is None:
        return
    if name == "SessionStart":
        ensure_running()
    request("/event", {"type": etype})
    if name == "UserPromptSubmit":
        result = request("/praise/take", {})
        count = result.get("count", 0) if isinstance(result, dict) else 0
        if isinstance(count, int) and count > 0 and inject_praise_enabled():
            line = (f"[Shion 桌宠] 自你上次回复后，用户通过摸 Shion 的头表扬了你 {count} 次。"
                    "可以自然地回应，不必刻意。\n")
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
