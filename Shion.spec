# Windows onedir；执行 .venv\Scripts\python tools\build.py。
from pathlib import Path
import sys

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from tools.build import windows_version_info
from tools.v3_bundle_files import spec_datas

assets = root / "assets"
datas = [(str(assets / name), "assets") for name in ("affection.json", "pricing.json", "weekly_titles.json")]
datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
for directory in ("lines", "menu"):
    datas += [(str(p), f"assets/{directory}") for p in sorted((assets / directory).glob("*.json"))]
# 运行期素材按 tools/v3_bundle_files.py 的清单显式收（V3 零件 / scene、fx_z、周报立绘）；
# 不递归收集 raw、parts、草稿、备份等素材源文件。清单由 tests/test_v3_runtime_files.py 取证核对。
datas += spec_datas(root)
datas += [(str(p), "assets/icon") for p in sorted((assets / "icon").glob("*.png"))]

a = Analysis(
    [str(root / "shion" / "__main__.py")],
    pathex=[str(root)],
    binaries=[], datas=datas,
    hiddenimports=[
        "hooks.shion_hook", "hooks.shion_statusline", "tools.hooks_config", "shion.console_send", "shion.bundle_check",
        # V3：多数在函数内导入
        *[f"shion.v3_{name}" for name in ("window", "display", "layers", "prewarm", "memory", "scene", "scene_view")],
        *[f"v3proto.{name}" for name in ("render", "animation", "cheek", "face", "mirror", "motion", "reaction",
                                         "reaction_face", "sampling", "stars", "surface", "head_touch", "tickle", "lift")],
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        # 运行期只用 scipy.ndimage（及其依赖 _lib / linalg / sparse / special）；
        # 下面这些子包在 build/v300/r4/trace.json 的全状态运行里一个模块都没加载过。
        "scipy.cluster", "scipy.constants", "scipy.datasets", "scipy.differentiate", "scipy.fft", "scipy.fftpack",
        "scipy.integrate", "scipy.interpolate", "scipy.io", "scipy.misc", "scipy.odr", "scipy.optimize",
        "scipy.signal", "scipy.spatial", "scipy.stats",
        # Pillow 只读写 PNG：去掉 AVIF / WebP / Tk 的原生扩展（_avif 一个就近 8 MB）
        "PIL._avif", "PIL._webp", "PIL._imagingtk", "PIL.ImageTk",
        "pytest", "tkinter", "matplotlib",
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
