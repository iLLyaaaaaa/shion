r"""Windows: .venv\Scripts\python tools\build.py（构建、统计并隔离自检）。"""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def build_environment() -> dict[str, str]:
    """不让 PATH 中其他应用的同名 DLL（例如 Poppler ICU）污染依赖分析。"""
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in ("PYTHONPATH", "PYTHONHOME", "QML2_IMPORT_PATH")
           and not key.upper().startswith(("QT_", "PYSIDE"))}
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows)))
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and check the Shion Windows onedir bundle")
    parser.add_argument("--check-only", action="store_true", help="只对已构建产物重新自检")
    args = parser.parse_args()
    if os.name != "nt" or struct.calcsize("P") != 8:
        parser.error("请使用 64 位 Windows Python 构建")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    bundle = ROOT / "dist" / "Shion"
    try:
        if not args.check_only:
            requirements = [line.strip().split("==") for line in (ROOT / "requirements-build.txt").read_text(
                encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
            def matches(name, wanted):
                try:
                    return version(name) == wanted
                except PackageNotFoundError:
                    return False
            if not all(matches(name, wanted) for name, wanted in requirements):
                print("Installing pinned build dependencies ...", flush=True)
                with (build / "dependencies.log").open("wb") as log:
                    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                                    str(ROOT / "requirements-build.txt")], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
            print("Building dist/Shion/Shion.exe ... (build/pyinstaller.log)", flush=True)
            with (build / "pyinstaller.log").open("wb") as log:
                subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                                "--distpath", str(ROOT / "dist"), "--workpath", str(build / "pyinstaller"),
                                str(ROOT / "Shion.spec")], cwd=ROOT, stdout=log,
                               stderr=subprocess.STDOUT, env=build_environment(), check=True)
        if not (bundle / "Shion.exe").is_file():
            raise FileNotFoundError(bundle / "Shion.exe")
        files = sorted((p for p in bundle.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size, reverse=True)
        total = sum(p.stat().st_size for p in files)
        groups: dict[str, int] = {}
        for p in files:
            rel = p.relative_to(bundle)
            group = "/".join(rel.parts[:2]) if len(rel.parts) > 2 else rel.as_posix()
            groups[group] = groups.get(group, 0) + p.stat().st_size
        report = {"bytes": total, "MB": round(total / 1_000_000, 2), "MiB": round(total / 1024**2, 2),
                  "over_150_MB": total > 150_000_000, "files": len(files),
                  "largest": [{"path": p.relative_to(bundle).as_posix(), "bytes": p.stat().st_size} for p in files[:10]],
                  "groups": dict(sorted(groups.items(), key=lambda pair: pair[1], reverse=True)),
                  "versions": {name: version(name) for name in ("PyInstaller", "pyinstaller-hooks-contrib", "PySide6", "numpy")}}
        (build / "size-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Bundle: {report['MB']} MB / {report['MiB']} MiB ({total} bytes, {len(files)} files)", flush=True)
        if report["over_150_MB"]:
            print("Over 150 MB; largest files (see build/size-report.json):", flush=True)
            for item in report["largest"]:
                print(f"  {item['bytes'] / 1_000_000:.2f} MB  {item['path']}")
            print("Qt is limited to Core/Gui/Widgets/Network; review any unexpected Qt DLLs/plugins before further exclusions.")
        sys.path.insert(0, str(ROOT))
        from tools.bundle_smoke import check_bundle
        print("Checking relocated bundle ...", flush=True)
        result = check_bundle(bundle, build / "bundle-check")
        print(f"PASS: {len(result['checks'])} checks; evidence: build/bundle-check", flush=True)
        return 0
    except Exception as exc:
        print(f"Build/check failed: {exc}\nSee build/*.log and build/bundle-check.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
