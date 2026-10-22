"""Claude Code hook 脚本：把事件转发给本机的 Shion 桌宠。

只用标准库。无论发生什么都返回 0、不输出多余内容，绝不能影响 Claude Code。
用法：shion_hook.py <SessionStart|UserPromptSubmit|PreToolUse|PostToolUse|PostToolUseFailure|PermissionRequest|Stop|Notification>

停下/继续：PreToolUse 和 PostToolUse 两个检查点在用户点了“停下”时原地等，点“继续”或在 CC 里说话就放行；
等满上限输出 continue=false 结束这一轮。诗音没开、连不上、出错一律放行。
立即中断：诗音结束正在跑的工具子进程，并让这个会话的下一个检查点（PreToolUse / PostToolUse）输出 continue=false。
会话：每个事件都带 stdin 里的 session_id；prompt / PreToolUse 另带启动本 hook 的 CC 进程（按实际父进程链确认）。
同意/否决：PermissionRequest 把要执行的内容交给诗音，等用户在诗音上点按钮；只有收到明确的 allow 才输出 allow，
其余一切情况（诗音没开、超时、出错、返回内容不对）都不输出任何决定，交回 CC 自己的授权框。
用户在 CC 里自己答了授权：同一会话的 PostToolUse / PostToolUseFailure（按工具名 + 参数配对）让诗音马上收起面板。
ExitPlanMode 仅发送 plan_ready 提醒，不登记授权请求，计划确认始终由 CC 自己处理。
反馈队列：PostToolUse（工作中）和 UserPromptSubmit（空闲时）把诗音里攒的反馈作为附加上下文送出。
"""
import hashlib
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
    "PermissionRequest": None,
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
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
STOP_REASON = "用户通过诗音让这一轮工作停下，请等待用户指示"
TIMEOUT_REASON = "用户很久没有回应，这一轮先结束，请等待用户指示"


def pause_limit() -> int:
    return remote_setting("pause_timeout", 1800, 60, 1880)


def pause_gate(limit: float, poll: float = PAUSE_POLL, session=None):
    """检查点（PreToolUse / PostToolUse）。用户点了“停下”后在这里原地等，直到在诗音上选择。

    返回 None = 放行（选了“继续”或在 CC 里说了话）；("stop", 理由) = 选了“结束这一轮”；
    ("timeout", 理由) = 等满上限，按“结束这一轮”处理。
    诗音没开、请求失败、返回内容不对，都按“没暂停、没停下”处理，绝不把 CC 卡住。
    """
    extra = {"session": session} if session else {}
    result = request("/pause/wait", {"wait": 0, **extra})
    deadline = time.monotonic() + limit
    while True:
        if not isinstance(result, dict):
            return None
        if result.get("stop") is True:
            return ("stop", ui_text("hook_stop", STOP_REASON))
        if result.get("paused") is not True:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            request("/event", {"type": "pause_timeout", **extra})
            return ("timeout", ui_text("hook_stop_timeout", TIMEOUT_REASON))
        wait = min(poll, remaining)
        result = request("/pause/wait", {"wait": wait, **extra}, timeout=wait + 3)


# ---------------------------------------------------------------- 找到启动本 hook 的 CC 进程
CC_NAMES = ("claude.exe", "node.exe", "bun.exe")
CHAIN_MAX = 8


def _winproc():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shion import winproc  # 只用标准库 ctypes，不 import Qt
    return winproc


def process_table() -> dict:
    """{pid: (父 pid, 可执行文件名)}，见 shion/winproc.py。出错返回空 dict。"""
    try:
        return _winproc().process_table()
    except Exception:
        return {}


def process_created(pid: int):
    try:
        return _winproc().process_created(pid)
    except Exception:
        return None


def find_cc_process(table=None, me=None, claude_pid=None, created=process_created):
    """从本进程沿父进程链往上找 CC 进程：有 CLAUDE_PID 时必须在链上找到它，否则取最近的 claude/node/bun。

    返回 {"pid", "created", "name", "entry", "hooks": [本 hook 到 CC 之间的 pid]}，找不到返回 None。
    """
    table = process_table() if table is None else table
    pid = os.getpid() if me is None else me
    if claude_pid is None:
        raw = os.environ.get("CLAUDE_PID", "")
        claude_pid = int(raw) if raw.isdigit() else None
    chain = []
    while pid in table and pid not in chain and len(chain) < CHAIN_MAX:
        chain.append(pid)
        parent = table[pid][0]
        if parent not in table:
            return None
        name = table[parent][1].lower()
        if (claude_pid is None or parent == claude_pid) and name in CC_NAMES:
            when = created(parent)
            if not when:
                return None
            entry = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "")[:40]
            return {"pid": parent, "created": when, "name": name, "entry": entry, "hooks": chain}
        pid = parent
    return None


PERMISSION_POLL = 10.0
FEEDBACK_TIMEOUT = 3.0
DETAIL_LIMIT = 12000  # 超出上限的授权内容不发送，交回 CC 自己处理


def permission_limit() -> int:
    return remote_setting("permission_timeout", 120, 10, 170)


def _clip(text, limit: int = DETAIL_LIMIT) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_permission(tool_name, tool_input, limit: int = DETAIL_LIMIT) -> str:
    """把要授权的操作写成给人看的文字：命令、文件完整路径、网址等。"""
    ti = tool_input if isinstance(tool_input, dict) else {}
    kind = TOOL_KIND.get(tool_name, "other")
    if kind == "bash" and ti.get("command"):
        desc = ti.get("description")
        return _clip(str(ti["command"]) + (f"\n# {desc}" if desc else ""), limit)
    if kind in ("edit", "write") and (ti.get("file_path") or ti.get("notebook_path")):
        return _clip(ti.get("file_path") or ti.get("notebook_path"), limit)
    if tool_name == "WebFetch" and ti.get("url"):
        return _clip(ti["url"], limit)
    if tool_name == "WebSearch" and ti.get("query"):
        return _clip(ti["query"], limit)
    try:
        return _clip(json.dumps(ti, ensure_ascii=False, indent=2), limit)
    except Exception:
        return _clip(ti, limit)


def ui_text(key: str, default: str) -> str:
    """按存档语言读 assets/lines 里的 ui 文字（给 CC 看的理由），读不到就用默认中文。"""
    lang = read_save().get("language")
    lang = lang if lang in ("zh", "en", "ja") else "zh"
    try:
        raw = json.loads((ROOT / "assets" / "lines" / f"{lang}.json").read_text(encoding="utf-8"))
        text = raw["ui"][key]
        return text if isinstance(text, str) and text else default
    except Exception:
        return default


def deny_message() -> str:
    return ui_text("hook_deny", "用户通过诗音否决了这个操作")


def permission_key(tool_name, tool_input) -> str:
    """工具名 + 参数的指纹。PermissionRequest 没有 tool_use_id，靠它和随后的 PostToolUse 配对。"""
    raw = json.dumps([tool_name, tool_input], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _session_field(data: dict) -> dict:
    sid = data.get("session_id")
    return {"session": sid} if isinstance(sid, str) and 0 < len(sid) <= 128 else {}


def settle_permission(data: dict) -> None:
    """工具已经跑过（PostToolUse / PostToolUseFailure）：它的授权在 CC 里答过了，让诗音收起还挂着的面板。"""
    session = _session_field(data)
    if session:
        request("/permission/settle", {**session, "key": permission_key(data.get("tool_name"), data.get("tool_input"))})


def permission_decision(data: dict, limit: float, poll: float = PERMISSION_POLL):
    """返回 {"behavior": "allow"} / {"behavior": "deny", "message": …}，或 None（不给决定）。

    allow 只在服务器明确回答 status == "allow"（且 id 对得上）时才会出现。
    """
    tool = data.get("tool_name")
    if not isinstance(tool, str) or not tool or tool == "AskUserQuestion":
        return None  # 提问不是同意/否决，交给 CC
    if tool == "ExitPlanMode":
        sid = data.get("session_id")
        request("/event", {"type": "plan_ready", **({"session": sid} if isinstance(sid, str) and 0 < len(sid) <= 128 else {})})
        return None  # 只提醒去看计划，不登记、不轮询、不给决定
    if len(describe_permission(tool, data.get("tool_input"), limit=10**9)) > DETAIL_LIMIT:
        return None  # 内容长到面板放不下：用户看不全就不能替他决定，交回 CC 自己的授权框
    detail = describe_permission(tool, data.get("tool_input"))
    opened = request(
        "/permission/open",
        {"tool": tool, "detail": detail, **_session_field(data),
         "key": permission_key(tool, data.get("tool_input"))},
        timeout=2.0,
    )
    rid = opened.get("id") if isinstance(opened, dict) else None
    if not isinstance(rid, str) or not rid:
        return None
    deadline = time.monotonic() + limit
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            request("/permission/withdraw", {"id": rid})
            return None
        wait = min(poll, remaining)
        answer = request("/permission/wait", {"id": rid, "wait": wait}, timeout=wait + 3)
        if not isinstance(answer, dict) or answer.get("id") != rid:
            return None
        status = answer.get("status")
        if status == "allow":
            return {"behavior": "allow"}
        if status == "deny":
            return {"behavior": "deny", "message": deny_message()}
        if status != "pending":
            return None


def emit(obj) -> None:
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def take_feedback() -> str:
    # 超时要比 bridge 等 GUI 线程的时间（1.5 秒）长：否则 hook 先放弃、GUI 线程随后仍清空队列，反馈就丢了
    result = request("/feedback/take", {}, timeout=FEEDBACK_TIMEOUT)
    text = result.get("text") if isinstance(result, dict) else ""
    return text if isinstance(text, str) else ""


def launch_shion() -> None:
    frozen = getattr(sys, "frozen", False)
    exe = Path(sys.executable) if frozen else ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not exe.exists():
        return
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):  # CREATE_BREAKAWAY_FROM_JOB；被拒绝就去掉重试
        try:
            subprocess.Popen(
                [str(exe)] + ([] if frozen else ["-m", "shion"]),
                cwd=str(exe.parent if frozen else ROOT), creationflags=flags | extra,
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
    if name == "PostToolUseFailure":
        return _short(data.get("tool_name") or "", 40) or None
    if name == "Notification":
        kind = data.get("notification_type")  # 官方字段：permission_prompt / idle_prompt / …
        return _short(kind, 40) if isinstance(kind, str) and kind else None
    return None


def session_meta(name: str, data: dict) -> dict:
    """事件里附带的会话信息：session_id、tool_use_id；prompt / PreToolUse 附带 CC 进程。"""
    meta = {}
    for key, field in (("session", "session_id"), ("tool_id", "tool_use_id")):
        value = data.get(field)
        if isinstance(value, str) and value and len(value) <= 128:
            meta[key] = value
    if name in ("UserPromptSubmit", "PreToolUse"):
        try:
            proc = find_cc_process()
        except Exception:
            proc = None
        if proc:
            meta["proc"] = proc
    return meta


def main() -> None:
    data = read_input()
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in EVENTS:
        return
    etype = EVENTS[name]
    meta = session_meta(name, data)
    session = meta.get("session")
    if name in ("PostToolUse", "PostToolUseFailure"):
        settle_permission(data)  # 先做：PostToolUse 之后可能在检查点等很久
    if name == "PostToolUseFailure":
        # 不是检查点：实测（2.1.289）CC 不理会 PostToolUseFailure 返回的 continue=false，中断标记留给下一个检查点
        if data.get("is_interrupt"):
            request("/event", {"type": "tool_done", **meta})  # 用户在 CC 里按了 Esc：工具结束，不算出错
            return
    if name == "SessionStart":
        ensure_running()
    if name == "PostToolUse":
        # 检查点：工具做完、开始写文字之前也能停住；继续以后才取反馈，停下时反馈留给下一次 UserPromptSubmit
        gate = pause_gate(pause_limit(), session=session)
        if gate is not None:
            emit({"continue": False, "stopReason": gate[1]})
            return
        request("/event", {"type": "tool_done", **meta})
        text = take_feedback()
        if text:
            emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}})
        return
    if name == "PermissionRequest":
        decision = permission_decision(data, permission_limit())
        if decision is not None:
            emit({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}})
        return
    if name == "PreToolUse":
        gate = pause_gate(pause_limit(), session=session)
        if gate is not None:
            reason = gate[1]
            # 结束这一轮：continue=false（官方：优先于事件专属决定），同时 deny 保证这次工具不执行
            emit({"continue": False, "stopReason": reason, "hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }})
            return
    detail = build_detail(name, data)
    payload = {"type": etype, **meta}
    if detail is not None:
        payload["detail"] = detail[:MAX_DETAIL]
    request("/event", payload)
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


def run_hook(argv=None) -> int:
    if argv is not None:
        sys.argv = [sys.argv[0], *argv]
    # 总时限：服务器卡住（收了连接不回包）时 socket 超时只管单次操作，这里兜底强制退出
    worker = threading.Thread(target=_guarded_main, daemon=True)
    worker.start()
    event = sys.argv[1:2]
    # PreToolUse / PostToolUse 可能要等用户点“继续”，总时限 = 暂停上限 + 余量；其余事件很快
    worker.join(12 if event == ["SessionStart"] else (pause_limit() + 30 if event in (["PreToolUse"], ["PostToolUse"]) else (permission_limit() + 10 if event == ["PermissionRequest"] else (6.0 if event == ["UserPromptSubmit"] else 2.5))))
    try:
        sys.stdout.flush()
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    os._exit(run_hook())
