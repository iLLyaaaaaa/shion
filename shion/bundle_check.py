"""打包自检专用入口：在隔离临时 HOME 中调用真正冻结的连接服务。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


def isolated_home(value: str) -> Path:
    home = Path(value).resolve(strict=True)
    temporary = Path(tempfile.gettempdir()).resolve()
    if home == temporary or not home.is_relative_to(temporary):
        raise ValueError("自检 HOME 必须是系统临时目录下的独立目录")
    for key in ("HOME", "USERPROFILE"):
        if not os.environ.get(key) or Path(os.environ[key]).resolve() != home:
            raise ValueError(f"自检要求隔离 {key}")
    if Path.home().resolve() != home:
        raise ValueError("自检 HOME 与 Path.home 不一致")
    combined = os.environ.get("HOMEDRIVE", "") + os.environ.get("HOMEPATH", "")
    if not combined or Path(combined).resolve() != home:
        raise ValueError("自检要求隔离 HOMEDRIVE/HOMEPATH")
    for key in ("APPDATA", "SHION_DATA_DIR"):
        value = os.environ.get(key)
        if (key == "APPDATA" and not value) or (value and not Path(value).resolve().is_relative_to(home)):
            raise ValueError(f"自检要求隔离 {key}")
    return home


def check_connection(value: str) -> dict:
    if not getattr(sys, "frozen", False):
        raise ValueError("此入口只用于冻结程序自检")
    home = isolated_home(value)  # 任何读写前检查，不接受真实 HOME 或已有配置。
    from tools import hooks_config as hc

    bundle = Path(sys._MEIPASS).resolve()
    if not Path(hc.__file__).resolve().is_relative_to(bundle) or hc.ROOT.resolve() != bundle:
        raise RuntimeError("连接服务没有从当前包加载")
    connection = hc.HookConnection(project=home / "project" / ".claude" / "settings.local.json")
    if connection.user.exists() or connection.project.exists():
        raise ValueError("自检需要全新的临时配置目录")
    original = {"statusLine": {"command": "foreign.exe"}, "modelSettings": {"test": True},
                "unknown": ["保留"], "hooks": {"Stop": [{"hooks": [
                    {"type": "command", "command": "foreign.exe"}]}]}}
    project = hc.merge({"permissions": {"allow": ["Read"]}}, "python.exe",
                       (home / "old" / "hooks" / "shion_hook.py").as_posix())
    for path, content in ((connection.user, original), (connection.project, project)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    checks = []

    def require(condition, name):
        if not condition:
            raise RuntimeError(f"连接自检失败：{name}")
        checks.append(name)

    installed = None
    for language in hc.LANGS:
        result = connection.connect(language)
        installed = hc.load(connection.user)
        require(connection.inspect().state == "connected", f"connect-{language}")
        require(hc.remove(installed) == original, f"preserve-{language}")
        require(hc.load(connection.project) == hc.remove(project), f"migrate-{language}")
        require(all(backup.is_file() for backup in result.backups), f"backups-{language}")
        own = [h for groups in installed["hooks"].values() for group in groups
               for h in group["hooks"] if hc._is_shion(h)]
        require(len(own) == len(hc.EVENTS) and all(
            h["command"] == Path(sys.executable).resolve().as_posix() and h["args"][0] == "--hook"
            for h in own), f"exe-path-{language}")
        expected = json.loads((bundle / "assets" / "lines" / f"{language}.json").read_text(encoding="utf-8"))
        require(all(h["statusMessage"] == expected["ui"][hc.STATUS_KEY] for h in own
                    if h["args"][1] in hc.STATUS_EVENTS), f"resources-{language}")
        before = connection.user.read_bytes()
        require(connection.connect(language) == hc.WriteResult((), ()) and
                connection.user.read_bytes() == before, f"idempotent-{language}")
    # 缺失的旧 exe 路径必须能被识别、修复。
    installed["hooks"]["SessionStart"][0]["hooks"][0]["command"] = (home / "missing" / "Shion.exe").as_posix()
    connection.user.write_text(json.dumps(installed), encoding="utf-8")
    require(connection.inspect().state == "stale", "stale")
    connection.connect()
    require(connection.inspect().state == "connected", "repair")
    connection.disconnect()
    require(hc.load(connection.user) == original and connection.inspect().state == "disconnected", "disconnect")
    require(hc.load(connection.project) == hc.remove(project), "no-project-restore")
    require(connection.disconnect() == hc.WriteResult((), ()), "disconnect-idempotent")
    # PyInstaller 的 Qt 运行时 hook 会先加载 QtCore 注册资源；业务分派不得加载 GUI。
    require(not any(name in sys.modules for name in ("PySide6.QtGui", "PySide6.QtWidgets")), "no-gui-import")
    return {"ok": True, "checks": checks, "executable": sys.executable, "bundle": str(bundle),
            "module": hc.__file__, "sys_path": sys.path}


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 1:
            raise ValueError("需要一个隔离的临时 HOME 参数")
        result = check_connection(argv[0])
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0
