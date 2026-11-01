"""把右键菜单（含展开的子菜单）离屏渲染成 PNG，并导出菜单树用于新旧对照。

    python tools/render_menu.py [--out build/menu-shots] [--baseline c6889c3]

不带 --worker 时是调度器：先把 --baseline 提交的 shion/assets/tools/hooks 导出到
<out>/_baseline-src，再对 新/旧 × 缩放 1 / 1.5 各起一个子进程渲染（QT_SCALE_FACTOR 必须在
QApplication 创建前设置）。所有用户目录、注册表、Codex 配置都换成临时对象，不读写真实环境。
输出：<out>/{new,old}/scale{1,1.5}/{lang}-{场景}-NN-*.png、*.json 菜单树，以及 <out>/mapping.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("zh", "en", "ja")
SCENARIOS = {
    # 名称: (Claude 连接状态, 连接 tooltip, 启用 ChatGPT, 开机自启是否失效, 工作中的 Claude 会话数)
    "plain": ("disconnected", "", False, False, 0),
    "connected": ("connected", "", True, False, 0),
    "stale": ("stale", "路径失效 / path is stale", True, True, 0),
    "one_session": ("connected", "", False, False, 1),
    "two_sessions": ("connected", "", False, False, 2),
    "same_project": ("connected", "", False, False, 2),
}
PROJECTS = ("my-app", "notes")  # 合成的项目文件夹名
# 场景 → 合成会话的 (文件夹名, 第一句话)；没列出的场景用 PROJECTS、不发第一句话
SESSION_SPECS = {
    "same_project": (("my-app", "Fix the login form validation"),
                     ("my-app", "Add dark mode to settings")),
}
PAYLOAD = ("shion", "assets", "tools", "hooks")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:40] or "x"


# ---------------------------------------------------------------- worker

def worker(source: Path, out: Path) -> int:
    scratch = Path(tempfile.mkdtemp(prefix="shion-menu-"))
    for name in ("HOME", "USERPROFILE"):
        os.environ[name] = str(scratch / "home")
    os.environ.update(APPDATA=str(scratch / "home" / "AppData"), SHION_DATA_DIR=str(scratch / "data"),
                      CODEX_HOME=str(scratch / "codex"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(source))

    from types import SimpleNamespace
    from datetime import datetime
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from shion import state as S
    from shion.chatgpt import ChatGPTConnection
    from shion.controller import PetController
    from shion.effects import HeartOverlay
    from shion.lines import Lines
    from shion.pet_window import PetWindow
    from shion.startup import Startup
    from tools.hooks_config import HookConnection

    class FakeRegistry:
        HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = "HKCU", 1, 2, 1

        def __init__(self):
            self.values = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def OpenKey(self, hive, path, reserved=0, access=0):
            return self

        CreateKeyEx = OpenKey

        def QueryValueEx(self, key, name):
            if name not in self.values:
                raise FileNotFoundError(name)
            return self.values[name]

        def SetValueEx(self, key, name, reserved, kind, value):
            self.values[name] = (value, kind)

        def DeleteValue(self, key, name):
            self.values.pop(name, None)

    app = QApplication.instance() or QApplication([])
    out.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 19, 12, 0, 0)
    written = []
    ratio_seen = [1.0]

    def render_chain(chain, path):
        """chain: [(菜单, 通向下一级的动作 or None), …]；父级高亮该项，子菜单与其顶端对齐并排。"""
        shots, x, offset_y, height, ratio = [], 0, 0, 0, 1.0
        for menu, active in chain:
            menu.setActiveAction(active)
            menu.ensurePolished()
            menu.adjustSize()
            pix = menu.grab()
            ratio = pix.devicePixelRatio() or 1.0
            ratio_seen[0] = ratio
            w, h = round(pix.width() / ratio), round(pix.height() / ratio)
            shots.append((pix, x, offset_y))
            height = max(height, offset_y + h)
            if active is not None:
                geo: QRect = menu.actionGeometry(active)
                offset_y += geo.y()
            x += w + 4
        canvas = QImage(round(x * ratio), round(height * ratio), QImage.Format_ARGB32_Premultiplied)
        canvas.setDevicePixelRatio(ratio)
        canvas.fill(QColor("#e9e9e9"))
        painter = QPainter(canvas)
        for pix, px, py in shots:
            painter.drawPixmap(px, py, pix)
        painter.end()
        assert canvas.save(str(path), "PNG") and path.stat().st_size > 0, path
        written.append(path)

    def walk(menu, ids, path, chain, texts, entries, shots):
        """深度优先：记录菜单树，并为每个（子）菜单渲染一张。"""
        shots.append((chain, path))
        for act in menu.actions():
            if act.isSeparator():
                continue
            ident = ids.get(act.text(), "text:" + act.text())
            entries.append({"id": ident, "text": act.text(), "path": path, "texts": texts,
                            "menu": act.menu() is not None, "checkable": act.isCheckable(),
                            "checked": act.isChecked(), "enabled": act.isEnabled(),
                            "tooltip": act.toolTip() if act.toolTip() != act.text() else ""})
            if act.menu() is not None:
                walk(act.menu(), ids, path + [ident], chain[:-1] + [(menu, act), (act.menu(), None)],
                     texts + [act.text()], entries, shots)

    for scenario, (state_name, detail, with_chatgpt, startup_stale, n_sessions) in SCENARIOS.items():
        for lang in LANGS:
            path = scratch / f"{scenario}-{lang}"
            path.mkdir(parents=True)
            data = S.load(path / "state.json")
            scheduler = S.SaveScheduler(path / "state.json", data)
            pet_state = S.PetState(data, now, on_change=scheduler.mark_dirty)
            mono = [100.0]
            win = PetWindow(height=200, clock=lambda: mono[0], autostart=False)
            overlay = HeartOverlay(clock=lambda: mono[0], autostart=False)
            ctl = PetController(win, pet_state, scheduler, lines=Lines(lang), overlay=overlay,
                                now_fn=lambda: now, say=lambda *_: None, autostart=False)
            registry = FakeRegistry()
            if startup_stale:
                registry.values["Shion"] = ("old", 1)
            ctl.startup = Startup(registry=registry, root=path)
            ctl.connection = HookConnection(path / "claude" / "settings.json", path / "project.json", path)
            ctl.connection.inspect = lambda s=state_name, d=detail: SimpleNamespace(state=s, detail=d)
            if with_chatgpt:
                ctl.chatgpt = ChatGPTConnection(path / "chatgpt", path / "codex")
            ctl.set_language(lang)
            specs = SESSION_SPECS.get(scenario) or tuple((PROJECTS[i], None) for i in range(n_sessions))
            for i, (project, prompt) in enumerate(specs):  # 合成的工作中会话（只给菜单看，不碰真实 CC）
                if prompt:
                    ctl.handle_event("prompt", None, {"session": f"s{i}", "project": project, "prompt_head": prompt})
                ctl.handle_event("working", json.dumps({"tool": "bash", "target": ""}),
                                 {"session": f"s{i}", "tool_id": f"t{i}", "project": project})

            ids = {}
            real_ui = ctl.lines.ui

            def recording_ui(key, **kw):
                text = real_ui(key, **kw)
                ids.setdefault(text, key)
                return text

            ctl.lines.ui = recording_ui  # build_menu 开头 `ui = self.lines.ui`：这样能把文案还原成 key
            menu = ctl.build_menu()
            entries, shots = [], []
            top_titles = [a.text() for a in menu.actions() if not a.isSeparator()]
            walk(menu, ids, [], [(menu, None)], [], entries, shots)
            (out / f"{lang}-{scenario}.json").write_text(
                json.dumps({"top_level": len(top_titles), "platform": app.platformName(), "dpr": ratio_seen[0],
                            "entries": entries}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            for n, (chain, p) in enumerate(shots):
                name = "top" if not p else "-".join(slug(i) for i in p[-2:])
                render_chain(chain, out / f"{lang}-{scenario}-{n:02d}-{name}.png")
            menu.deleteLater()
            ctl.lines.ui = real_ui
            ctl.dispose()
            overlay.close()
            win.close()
    print(f"{out}: {len(written)} png")
    return 0


# ---------------------------------------------------------------- orchestrator

def export_baseline(ref: str, target: Path) -> None:
    if target.exists():
        import shutil
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", ref, *PAYLOAD], cwd=ROOT, check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)


def mapping_table(out: Path) -> str:
    rows, missing = [], []
    for scenario in SCENARIOS:
        for lang in ("zh",):
            if not (out / "old" / "scale1" / f"{lang}-{scenario}.json").exists():
                continue  # 旧版本没有这个场景
            old = json.loads((out / "old" / "scale1" / f"{lang}-{scenario}.json").read_text(encoding="utf-8"))
            new = json.loads((out / "new" / "scale1" / f"{lang}-{scenario}.json").read_text(encoding="utf-8"))
            index = {e["id"]: e for e in new["entries"]}
            rows.append(f"\n### 场景 {scenario}（顶层：旧 {old['top_level']} 项 → 新 {new['top_level']} 项）\n")
            rows.append("| 旧位置 | 新位置 | 状态保留 |\n|---|---|---|")
            for e in old["entries"]:
                match = index.get(e["id"])
                old_path = " ▸ ".join(e["texts"] + [e["text"]]).replace("\n", " ⏎ ")
                if match is None and "\n" in e["text"]:
                    # 旧版把多行状态拼成一项；新版逐行拆开（被截断的行全文在 tooltip 里）
                    parts = [next((n for n in new["entries"] if n["path"][-1:] == e["path"][-1:] and line in (n["text"], n["tooltip"])), None)
                             for line in e["text"].split("\n")]
                    if all(p is not None and not p["enabled"] for p in parts):
                        rows.append(f"| {old_path} | {' ▸ '.join(parts[0]['texts'])} ▸ 拆成 {len(parts)} 行禁用项 | 是 |")
                        continue
                if match is None:
                    missing.append(f"{scenario}: {old_path}")
                    rows.append(f"| {old_path} | **缺失** | |")
                    continue
                same = all(e[k] == match[k] for k in ("checkable", "checked", "enabled", "menu", "tooltip"))
                rows.append(f"| {old_path} | {' ▸ '.join(match['texts'] + [match['text']])} | {'是' if same else '否（见下）'} |")
                if not same:
                    missing.append(f"{scenario}: {old_path} 属性变化 {({k: (e[k], match[k]) for k in ('checkable', 'checked', 'enabled', 'menu', 'tooltip') if e[k] != match[k]})}")
    rows.append("\n缺失/变化：" + ("无" if not missing else "\n- " + "\n- ".join(missing)))
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "menu-shots")
    parser.add_argument("--baseline", metavar="REF", help="同时渲染这个提交里的旧菜单并生成对照表")
    parser.add_argument("--platform", choices=("offscreen", "windows"), default="offscreen",
                        help="offscreen 没有系统字体（默认只载入 C:/Windows/Fonts 里能被 Qt 读到的，中日文字形和宽度不准）；"
                             "windows 用真实字体渲染，菜单不会被显示，适合检查截断和宽度")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.worker:
        return worker(args.source, args.out)
    jobs = [("new", ROOT)]
    if args.baseline:
        export_baseline(args.baseline, args.out / "_baseline-src")
        jobs.append(("old", args.out / "_baseline-src"))
    for label, source in jobs:
        for scale in ("1", "1.5"):
            env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM=args.platform)
            if args.platform == "offscreen":
                env.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:/Windows"), "Fonts"))
            target = args.out / label / f"scale{scale}"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--source", str(source),
                            "--out", str(target)], check=True, env=env, cwd=source)
    if args.baseline:
        table = mapping_table(args.out)
        (args.out / "mapping.md").write_text(table, encoding="utf-8")
        print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
