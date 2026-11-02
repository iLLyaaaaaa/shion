# Windows onedir；执行 .venv\Scripts\python tools\build.py。
from pathlib import Path
import sys

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from tools.build import windows_version_info

assets = root / "assets"
datas = [(str(assets / name), "assets") for name in ("affection.json", "pricing.json", "weekly_titles.json")]
datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
for directory in ("lines", "menu"):
    datas += [(str(p), f"assets/{directory}") for p in sorted((assets / directory).glob("*.json"))]
# 只带运行图；不递归收集 raw、草稿、备份等素材源文件。
datas += [(str(p), "assets/sprites") for p in sorted((assets / "sprites").glob("*.png"))]
datas += [(str(p), "assets/icon") for p in sorted((assets / "icon").glob("*.png"))]

a = Analysis(
    [str(root / "shion" / "__main__.py")],
    pathex=[str(root)],
    binaries=[], datas=datas,
    hiddenimports=["hooks.shion_hook", "hooks.shion_statusline", "tools.hooks_config", "shion.console_send", "shion.bundle_check"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        "scipy", "PIL", "pytest", "tkinter", "matplotlib",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.QtSvg",
    ],
    noarchive=False,
)

# QtGui 的默认 hook 收集许多可选插件及其 DLL；本程序只读写 PNG（QtGui 内置）。
qt_dlls = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6network.dll"}
plugins = {"qwindows.dll", "qoffscreen.dll", "qmodernwindowsstyle.dll", "qwindowsvistastyle.dll"}
# QWidget/QPainter 不用 OpenGL；Qt TLS 插件已排除，标准库 _ssl 使用它自己的 OpenSSL 1.1。
unused_qt_extras = {"opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll"}

def needed(entry):
    name = entry[0].replace("\\", "/").lower()
    basename = name.rsplit("/", 1)[-1]
    if basename in unused_qt_extras:
        return False
    if "/plugins/" in name:
        return basename in plugins
    if basename.startswith("qt6") and basename.endswith(".dll"):
        return basename in qt_dlls
    return True

a.binaries = [entry for entry in a.binaries if needed(entry)]
# PyInstaller's PySide6 runtime hook imports QtCore before our entry point.
# Keep the upstream hook unchanged for GUI/hook modes, skip it only for the
# stdlib-only observer and statusLine relay. Generate the wrapper from the pinned installed hook.
import textwrap
for index, (name, source, kind) in enumerate(a.scripts):
    if name == "pyi_rth_pyside6":
        wrapper = root / "build" / "observer_lazy_qt.py"
        wrapper.parent.mkdir(exist_ok=True)
        wrapper.write_text("import sys\nif sys.argv[1:2] not in (['--codex-observer'], ['--statusline']):\n" +
                           textwrap.indent(Path(source).read_text(encoding="utf-8"), "    "), encoding="utf-8")
        a.scripts[index] = (name, str(wrapper), kind)
        break
else:
    raise RuntimeError("Expected pinned PySide6 runtime hook was not found")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Shion",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, contents_directory="_internal",
    icon=str(assets / "icon" / "shion.ico"), version=windows_version_info(),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Shion")
