"""发布产物的独立小图、窗口身份、PE 资源与 ZIP 完整性。"""
import hashlib
from pathlib import Path
import zipfile

from PIL import Image
import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMessageBox

from shion import __version__
from shion.icons import ICON_DIR, ICON_SIZES, application_icon
from tests.test_controller import qapp
from tools.build import create_release_zip, release_filename, windows_version_info
from tools.make_icon import generate_icons

ROOT = Path(__file__).resolve().parent.parent


def test_generated_icons_are_repeatable_and_ico_keeps_each_custom_frame(tmp_path):
    idle = ROOT / "assets/sprites/idle.png"
    before = hashlib.sha256(idle.read_bytes()).digest()
    first, second = tmp_path / "first", tmp_path / "second"
    generate_icons(first)
    generate_icons(second)
    assert {p.name for p in first.iterdir()} == {p.name for p in ICON_DIR.iterdir()}
    with Image.open(first / "shion.ico") as ico:
        assert ico.ico.sizes() == {(size, size) for size in ICON_SIZES}
        for size in ICON_SIZES:
            name = "shion.png" if size == 256 else f"shion-{size}.png"
            assert (first / name).read_bytes() == (second / name).read_bytes() == (ICON_DIR / name).read_bytes()
            with Image.open(first / name) as frame:
                assert frame.mode == "RGBA" and frame.size == (size, size)
                assert frame.getchannel("A").getextrema() == (0, 255)
                assert ico.ico.getimage((size, size)).convert("RGBA").tobytes() == frame.tobytes()
    assert (first / "shion.ico").read_bytes() == (second / "shion.ico").read_bytes() == (ICON_DIR / "shion.ico").read_bytes()
    assert hashlib.sha256(idle.read_bytes()).digest() == before


def test_application_identity_and_inherited_window_icons(qapp, monkeypatch):
    from shion import app
    from shion.pet_window import PetWindow

    previous = (qapp.applicationName(), qapp.applicationVersion(), qapp.windowIcon())
    monkeypatch.setattr(app.SingleInstance, "acquire", lambda _: False)
    win = box = None
    try:
        assert app.run() == 0  # 在单实例检查处退出，不启动服务或访问存档。
        assert qapp.applicationName() == "Shion" and qapp.applicationVersion() == __version__ == "1.0.0"
        icon = application_icon()
        assert sorted(s.width() for s in icon.availableSizes()) == sorted(ICON_SIZES)
        win, box = PetWindow(autostart=False), QMessageBox()
        assert win.windowTitle() == "Shion"
        for size in ICON_SIZES:
            expected = icon.pixmap(QSize(size, size), 1.0).toImage()
            assert not expected.isNull()
            assert win.windowIcon().pixmap(QSize(size, size), 1.0).toImage() == expected
            assert box.windowIcon().pixmap(QSize(size, size), 1.0).toImage() == expected
    finally:
        if win is not None:
            win.close()
        if box is not None:
            box.close()
        qapp.setApplicationName(previous[0])
        qapp.setApplicationVersion(previous[1])
        qapp.setWindowIcon(previous[2])


def test_windows_version_resource_round_trip():
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo

    resource = VSVersionInfo()
    resource.fromRaw(windows_version_info().toRaw())
    assert resource.ffi.fileVersionMS == resource.ffi.productVersionMS == 1 << 16
    assert resource.ffi.fileVersionLS == resource.ffi.productVersionLS == 0
    fields = {item.name: item.val for item in resource.kids[0].kids[0].kids}
    assert fields["ProductName"] == fields["FileDescription"] == "Shion"
    assert fields["CompanyName"] == "iLLyaaaaaa"
    assert fields["FileVersion"] == fields["ProductVersion"] == __version__


def test_zip_contains_exact_bundle_and_licenses_with_stable_bytes(tmp_path):
    bundle, licenses = tmp_path / "bundle", tmp_path / "licenses"
    (bundle / "_internal").mkdir(parents=True)
    (licenses / "assets").mkdir(parents=True)
    (bundle / "Shion.exe").write_bytes(b"exe")
    (bundle / "_internal" / "data.bin").write_bytes(b"runtime\0data")
    (licenses / "LICENSE").write_bytes(b"MIT")
    (licenses / "assets/LICENSE").write_bytes(b"CC BY-NC 4.0")
    (licenses / "secret.env").write_bytes(b"must not be included")
    output = tmp_path / release_filename()
    assert output.name == "Shion-1.0.0-win64.zip"
    report = create_release_zip(bundle, output, licenses)
    before = output.read_bytes()
    with zipfile.ZipFile(output) as archive:
        assert len(archive.namelist()) == 4
        assert set(archive.namelist()) == {"Shion/Shion.exe", "Shion/_internal/data.bin", "LICENSE", "assets/LICENSE"}
        assert archive.testzip() is None
        assert archive.read("Shion/_internal/data.bin") == b"runtime\0data"
        assert archive.read("LICENSE") == b"MIT" and archive.read("assets/LICENSE") == b"CC BY-NC 4.0"
    assert report["bytes"] == len(before) and report["sha256"] == hashlib.sha256(before).hexdigest()
    assert create_release_zip(bundle, output, licenses) == report and output.read_bytes() == before
    (licenses / "assets/LICENSE").unlink()
    with pytest.raises(ValueError):
        create_release_zip(bundle, output, licenses)
    assert output.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
