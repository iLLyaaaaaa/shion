r"""Windows: .venv\Scripts\python tools\build.py（构建、统计并隔离自检）。"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def windows_version_info():
    """直接读取唯一应用版本源，交给 PyInstaller 写入 exe 的版本资源。"""
    from shion import __version__
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

    fixed = tuple(int(part) for part in __version__.split(".")) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=fixed, prodvers=fixed, mask=0x3f, flags=0,
                          OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "iLLyaaaaaa"),
            StringStruct("FileDescription", "Shion"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", "Shion"),
            StringStruct("LegalCopyright", "Copyright (c) 2026 iLLyaaaaaa"),
            StringStruct("OriginalFilename", "Shion.exe"),
            StringStruct("ProductName", "Shion"),
            StringStruct("ProductVersion", __version__),
        ])]), VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])


def release_filename() -> str:
    from shion import __version__
    return f"Shion-{__version__}-win64.zip"


def create_release_zip(bundle: Path, output: Path, license_root: Path = ROOT) -> dict:
    """只收完整运行目录及两份许可；验证后原子替换 ZIP，固定时间戳便于复核。"""
    if not (bundle / "Shion.exe").is_file():
        raise FileNotFoundError(bundle / "Shion.exe")
    sources = [(p, "Shion/" + p.relative_to(bundle).as_posix())
               for p in sorted(bundle.rglob("*")) if p.is_file()]
    sources += [(license_root / "LICENSE", "LICENSE"), (license_root / "assets/LICENSE", "assets/LICENSE")]
    for path, _ in sources:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"缺失或不支持的打包文件：{path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip.tmp", delete=False) as temporary:
        staging = Path(temporary.name)
    try:
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, name in sources:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(staging) as archive:
            if archive.testzip() is not None or archive.namelist() != [name for _, name in sources]:
                raise ValueError("ZIP 完整性检查失败")
            for path, name in sources:
                if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256(path.read_bytes()).digest():
                    raise ValueError(f"ZIP 文件内容不一致：{name}")
        staging.replace(output)
    finally:
        staging.unlink(missing_ok=True)
    return {"file": output.name, "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "files": len(sources)}


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
        from shion import __version__
        result = check_bundle(bundle, build / "bundle-check", __version__)
        print(f"PASS: {len(result['checks'])} checks; evidence: build/bundle-check", flush=True)
        if not args.check_only:
            release = create_release_zip(bundle, ROOT / "dist" / release_filename())
            (build / "release-report.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
            print(f"ZIP: dist/{release['file']} ({release['bytes']} bytes)\nSHA-256: {release['sha256']}", flush=True)
        return 0
    except Exception as exc:
        print(f"Build/check failed: {exc}\nSee build/*.log and build/bundle-check.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
