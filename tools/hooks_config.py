"""安装/卸载 Shion hooks 的共用逻辑（纯函数 + 读写 settings 文件）。只用标准库。"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

MARKER = "shion_hook.py"
ROOT = Path(__file__).resolve().parent.parent
EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "Stop",
    "Notification",
]
TIMEOUTS = {"SessionStart": 15, "PreToolUse": 1900, "PostToolUse": 1900, "PermissionRequest": 180}  # 要等用户点按钮，比各自的等待上限长
DEFAULT_TIMEOUT = 5
# 检查点：停下时会一直停在这里，CC 转圈处显示这段文字（官方 hooks 字段 statusMessage）
STATUS_EVENTS = ("PreToolUse", "PostToolUse")
STATUS_KEY = "hook_status_waiting"
STATUS_DEFAULT = "诗音在看着～（一直停在这里就是暂停了，右键诗音点继续）"
LANGS = ("zh", "en", "ja")


def default_python(root: Path = ROOT) -> str:
    """hook 用项目 .venv 里的 python 的绝对路径（exec 形式：不经过 shell，路径带空格也不用引号）。"""
    exe = root / ".venv" / "Scripts" / "python.exe"
    if not exe.exists():
        raise ValueError(f"找不到 {exe}，请先建好 .venv")
    return exe.as_posix()


def default_hook_script(root: Path = ROOT) -> str:
    return (root / "hooks" / MARKER).as_posix()


def save_language() -> str:
    """存档里的语言（与 hooks/shion_hook.py 的 read_save / ui_text 同一规则），不是 zh/en/ja 就用 zh。"""
    try:
        directory = os.environ.get("SHION_DATA_DIR")
        path = (Path(directory) if directory else Path(os.environ["APPDATA"]) / "Shion") / "state.json"
        lang = json.loads(path.read_text(encoding="utf-8")).get("language")
    except Exception:
        lang = None
    return lang if lang in LANGS else "zh"


def status_message(lang: str, root: Path = ROOT) -> str:
    """检查点 hook 的 statusMessage：按语言读 assets/lines 的 ui 文字，读不到用中文默认。"""
    try:
        raw = json.loads((root / "assets" / "lines" / f"{lang}.json").read_text(encoding="utf-8"))
        text = raw["ui"][STATUS_KEY]
        return text if isinstance(text, str) and text else STATUS_DEFAULT
    except Exception:
        return STATUS_DEFAULT


def _is_shion(hook) -> bool:
    if not isinstance(hook, dict):
        return False
    return MARKER in str(hook.get("command", "")) or MARKER in " ".join(map(str, hook.get("args") or []))


def remove(settings: dict) -> dict:
    """返回去掉所有 Shion 条目的新 settings（不改入参）；清理空的组、事件和 hooks 键。"""
    out = json.loads(json.dumps(settings))
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept.append(group)
                continue
            rest = [h for h in inner if not _is_shion(h)]
            if len(rest) == len(inner):
                kept.append(group)
            elif rest:
                kept.append({**group, "hooks": rest})
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del out["hooks"]
    return out


def merge(settings: dict, python: str, script: str, status: str | None = None) -> dict:
    """返回加入 Shion hooks 的新 settings：先清掉旧的 Shion 条目，再追加，保留其他配置。

    status：给两个检查点（PreToolUse / PostToolUse）加的 statusMessage；None 不加。"""
    out = remove(settings)
    hooks = out.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings 里的 hooks 不是对象，拒绝修改")
    for event in EVENTS:
        entry = {
            "type": "command",
            "command": python,
            "args": [script, event],
            "timeout": TIMEOUTS.get(event, DEFAULT_TIMEOUT),
        }
        if status and event in STATUS_EVENTS:
            entry["statusMessage"] = status
        group = {"hooks": [entry]}
        if event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
            group = {"matcher": "*", **group}
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ValueError(f"hooks.{event} 不是数组，拒绝修改")
        existing.append(group)
    return out


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    if not isinstance(data, dict):
        raise ValueError("settings 文件不是 JSON 对象")
    return data


def save_with_backup(path: Path, data: dict) -> Path | None:
    """写前备份（原文件存在时），先写临时文件再替换。返回备份路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.shion-backup-{stamp}")
        shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def run(action: str, settings_path: str | None, python: str | None = None, script: str | None = None,
        lang: str | None = None) -> int:
    path = Path(settings_path) if settings_path else Path.home() / ".claude" / "settings.json"
    if action == "uninstall" and not path.exists():
        print(f"没有需要卸载的：{path} 不存在")
        return 0
    try:
        current = load(path)
        if action == "install":
            status = status_message(lang if lang in LANGS else save_language())
            new = merge(current, python or default_python(), script or default_hook_script(), status)
        else:
            new = remove(current)
        if new == current and path.exists():
            print(f"没有变化，未改动：{path}")
            return 0
        backup = save_with_backup(path, new)
    except (ValueError, OSError) as e:  # json.JSONDecodeError 是 ValueError
        print(f"失败：{path}（{e}）；原文件未被改写", file=sys.stderr)
        return 1
    print(f"已{'安装' if action == 'install' else '卸载'}：{path}" + (f"（备份：{backup.name}）" if backup else ""))
    return 0
