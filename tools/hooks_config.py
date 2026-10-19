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
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "Stop", "Notification"]
TIMEOUTS = {"SessionStart": 15}
DEFAULT_TIMEOUT = 5


def default_command_prefix(root: Path = ROOT) -> str:
    """命令必须以不带引号的词开头：Claude Code 在 Windows 上可能用 PowerShell 执行 hook，
    以 "路径" 开头会被当成字符串而解析失败。hook 脚本只用标准库，所以直接用 PATH 里的 python。"""
    hook = (root / "hooks" / MARKER).as_posix()
    if any(c in hook for c in '$`"'):
        raise ValueError(f"项目路径含 $、反引号或引号，PowerShell 下命令会出错：{hook}")
    found = shutil.which("python")
    if not found or "windowsapps" in found.lower():
        raise ValueError("PATH 里没有可用的 python（或只有 Microsoft Store 占位程序），hook 命令会失败")
    return f'python "{hook}"'


def _is_shion(hook) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


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


def merge(settings: dict, command_prefix: str) -> dict:
    """返回加入 Shion hooks 的新 settings：先清掉旧的 Shion 条目，再追加，保留其他配置。"""
    out = remove(settings)
    hooks = out.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings 里的 hooks 不是对象，拒绝修改")
    for event in EVENTS:
        entry = {
            "type": "command",
            "command": f"{command_prefix} {event}",
            "timeout": TIMEOUTS.get(event, DEFAULT_TIMEOUT),
        }
        group = {"hooks": [entry]}
        if event == "PreToolUse":
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


def run(action: str, settings_path: str | None, prefix: str | None = None) -> int:
    path = Path(settings_path) if settings_path else Path.home() / ".claude" / "settings.json"
    if action == "uninstall" and not path.exists():
        print(f"没有需要卸载的：{path} 不存在")
        return 0
    try:
        current = load(path)
        new = merge(current, prefix or default_command_prefix()) if action == "install" else remove(current)
        if new == current and path.exists():
            print(f"没有变化，未改动：{path}")
            return 0
        backup = save_with_backup(path, new)
    except (ValueError, OSError) as e:  # json.JSONDecodeError 是 ValueError
        print(f"失败：{path}（{e}）；原文件未被改写", file=sys.stderr)
        return 1
    print(f"已{'安装' if action == 'install' else '卸载'}：{path}" + (f"（备份：{backup.name}）" if backup else ""))
    return 0
