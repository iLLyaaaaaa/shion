"""安装/卸载 Shion hooks 的共用逻辑（纯函数 + 读写 settings 文件）。只用标准库。"""
from __future__ import annotations

import json
import os
import ntpath
import re
import shlex
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

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
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return False
    command, args = hook.get("command"), hook.get("args", [])
    if not isinstance(command, str) or not isinstance(args, list):
        return False
    # 兼容旧 shell 命令；只识别真正执行的脚本，不能按子串误删 echo/别人的脚本。
    if not args:
        try:
            parts = [p.strip('"\'') for p in shlex.split(command, posix=False)]
        except ValueError:
            return False
        if len(parts) != 3:
            return False
        command, args = parts[0], parts[1:]
    if len(args) != 2 or args[1] not in EVENTS or not isinstance(args[0], str):
        return False
    exe = ntpath.basename(command).lower()
    if exe == "shion.exe" and args[0] == "--hook":
        return True
    return bool(re.fullmatch(r"pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?", exe)) and ntpath.basename(args[0]).lower() == MARKER


def validate(settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("settings 文件不是 JSON 对象")
    if "hooks" not in settings:
        return
    hooks = settings["hooks"]
    if not isinstance(hooks, dict):
        raise ValueError("settings 里的 hooks 不是对象，拒绝修改")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} 不是数组，拒绝修改")
        for group in groups:
            if (not isinstance(group, dict) or not isinstance(group.get("hooks"), list)
                    or any(not isinstance(h, dict) for h in group["hooks"])):
                raise ValueError(f"hooks.{event} 分组格式无效，拒绝修改")


def remove(settings: dict) -> dict:
    """返回去掉所有 Shion 条目的新 settings（不改入参）；清理空的组、事件和 hooks 键。"""
    validate(settings)
    out = json.loads(json.dumps(settings))
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        event_changed = False
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept.append(group)
                continue
            rest = [h for h in inner if not _is_shion(h)]
            event_changed |= len(rest) != len(inner)
            if len(rest) == len(inner):
                kept.append(group)
            elif rest:
                kept.append({**group, "hooks": rest})
        if not event_changed:
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if changed and not hooks:
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
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    validate(data)
    return data


def save_with_backup(path: Path, data: dict) -> Path | None:
    """写前备份（原文件存在时），先写临时文件再替换。返回备份路径。"""
    result = apply_changes([(path, load(path), data)])
    return result.backups[0] if result.backups else None


class WriteResult(NamedTuple):
    changed: tuple[Path, ...]
    backups: tuple[Path, ...]


def _stage(path: Path, content: bytes) -> Path:
    fd, name = tempfile.mkstemp(prefix=path.name + ".shion-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        return tmp
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def apply_changes(edits: list[tuple[Path, dict, dict]]) -> WriteResult:
    """全部校验/备份/暂存后依次替换；失败时恢复本次已经替换的文件。"""
    staged, backups, written = [], [], []
    try:
        for path, before, after in edits:
            validate(after)
            if before == after:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            original = path.read_bytes() if path.exists() else None
            if load(path) != before:
                raise OSError(f"配置已被其他程序修改，请重试：{path}")
            if original is not None:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                backup = path.with_name(f"{path.name}.shion-backup-{stamp}")
                shutil.copy2(path, backup)
                if backup.read_bytes() != original:
                    raise OSError(f"备份期间配置发生变化，请重试：{path}")
                backups.append(backup)
            content = (json.dumps(after, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            staged.append((path, original, content, _stage(path, content)))
        for entry in staged:
            path, original, content, tmp = entry
            if (path.read_bytes() if path.exists() else None) != original:
                raise OSError(f"配置已被其他程序修改，请重试：{path}")
            os.replace(tmp, path)
            written.append(entry)
    except (ValueError, OSError) as exc:
        failures = []
        for path, original, content, _ in reversed(written):
            try:
                if path.read_bytes() != content:
                    raise OSError("配置再次发生变化，拒绝覆盖")
                if original is None:
                    path.unlink()
                else:
                    restore = _stage(path, original)
                    try:
                        os.replace(restore, path)
                    finally:
                        restore.unlink(missing_ok=True)
            except OSError as rollback:
                failures.append(f"{path}: {rollback}")
        if failures:
            raise OSError(f"{exc}；恢复失败：{'；'.join(failures)}；备份：{', '.join(map(str, backups))}") from exc
        raise
    finally:
        for _, _, _, tmp in staged:
            tmp.unlink(missing_ok=True)
    return WriteResult(tuple(e[0] for e in staged), tuple(backups))


def user_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def runtime_command(root: Path = ROOT) -> tuple[str, str]:
    """第二项是 args 的前缀：源码脚本或打包后的 --hook；保持原有 command + args 结构。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().as_posix(), "--hook"
    return default_python(root.resolve()), default_hook_script(root.resolve())


class ConnectionStatus(NamedTuple):
    state: str  # connected / disconnected / stale / error
    detail: str = ""


class HookConnection:
    """菜单与 CLI 共用的配置服务；构造不读文件，路径可全部注入。"""
    def __init__(self, user: Path | None = None, project: Path | None = None, root: Path = ROOT):
        self.user = user if user is not None else user_settings_path()
        self.project = project if project is not None else root / ".claude" / "settings.local.json"
        self.root = root

    def inspect(self) -> ConnectionStatus:
        try:
            settings = load(self.user)
            own = [(event, group, h) for event, groups in settings.get("hooks", {}).items()
                   for group in groups for h in group["hooks"] if _is_shion(h)]
            if not own:
                return ConnectionStatus("disconnected")
            if len(own) != len(EVENTS):
                return ConnectionStatus("stale")
            try:
                command, prefix = runtime_command(self.root)
            except ValueError:
                return ConnectionStatus("stale")
            if not Path(command).is_file() or (prefix != "--hook" and not Path(prefix).is_file()):
                return ConnectionStatus("stale")
            expected = merge({}, command, prefix)["hooks"]
            for event in EVENTS:
                matches = [(g, h) for e, g, h in own if e == event]
                want = expected[event][0]
                if len(matches) != 1:
                    return ConnectionStatus("stale")
                group, hook = matches[0]
                # statusMessage 的语言不影响是否已连接；保留安装时的语言规则。
                if (any(hook.get(k) != v for k, v in want["hooks"][0].items())
                        or group.get("matcher") != want.get("matcher")
                        or (event in STATUS_EVENTS and not isinstance(hook.get("statusMessage"), str))):
                    return ConnectionStatus("stale")
            return ConnectionStatus("connected")
        except (ValueError, OSError) as exc:
            return ConnectionStatus("error", str(exc))

    def connect(self, lang: str = "zh") -> WriteResult:
        user, project = load(self.user), load(self.project)
        command, prefix = runtime_command(self.root)
        if not Path(command).is_file() or (prefix != "--hook" and not Path(prefix).is_file()):
            raise ValueError("诗音的运行路径已失效")
        installed = merge(user, command, prefix, status_message(lang, self.root))
        # 先移除旧项目条目，避免同一事件双发；失败由 apply_changes 恢复。
        return apply_changes([(self.project, project, remove(project)), (self.user, user, installed)])

    def disconnect(self) -> WriteResult:
        current = load(self.user)
        return apply_changes([(self.user, current, remove(current))])


def run(action: str, settings_path: str | None, python: str | None = None, script: str | None = None,
        lang: str | None = None) -> int:
    path = Path(settings_path) if settings_path else user_settings_path()
    if action == "uninstall" and not path.exists():
        print(f"没有需要卸载的：{path} 不存在")
        return 0
    try:
        if settings_path is None:
            connection = HookConnection()
            result = connection.connect(lang if lang in LANGS else save_language()) if action == "install" else connection.disconnect()
            print(f"已{'安装' if action == 'install' else '卸载'}：{path}" +
                  (f"（备份：{', '.join(map(str, result.backups))}）" if result.backups else ""))
            return 0
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
        outcome = "请按备份位置检查并恢复文件" if "恢复失败" in str(e) else "原文件未被改写"
        print(f"失败：{path}（{e}）；{outcome}", file=sys.stderr)
        return 1
    print(f"已{'安装' if action == 'install' else '卸载'}：{path}" + (f"（备份：{backup.name}）" if backup else ""))
    return 0
