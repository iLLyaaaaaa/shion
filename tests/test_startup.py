import subprocess
import sys

import pytest

from tests.conftest import FakeRegistry
from shion.startup import RUN_KEY, Startup, launch_args


@pytest.fixture
def startup(tmp_path):
    root = tmp_path / "诗音 app with spaces"
    for name in (".venv/Scripts/pythonw.exe", "shion/__main__.py"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"test")
    return Startup(FakeRegistry(), root)


def test_roundtrip_preserves_other_startup_values_and_quotes_paths(startup):
    startup.registry.values["OtherApp"] = ("keep", 1)
    assert startup.inspect() == "disabled"
    startup.set_enabled(True)
    assert startup.inspect() == "enabled"
    value = startup.read()
    assert value == subprocess.list2cmdline(launch_args(startup.root))
    assert value.startswith('"') and '" "' in value
    startup.set_enabled(False)
    startup.set_enabled(False)
    assert startup.inspect() == "disabled"
    assert startup.registry.values == {"OtherApp": ("keep", 1)}
    assert RUN_KEY == r"Software\Microsoft\Windows\CurrentVersion\Run"


def test_invalid_existing_command_is_repaired_and_missing_file_refused(startup):
    startup.registry.values["Shion"] = (r'C:\old\Shion.exe', 1)
    assert startup.inspect() == "stale"
    startup.set_enabled(True)
    assert startup.inspect() == "enabled"
    (startup.root / "shion/__main__.py").unlink()
    assert startup.inspect() == "stale"
    with pytest.raises(ValueError):
        startup.set_enabled(True)
    startup.set_enabled(False)


def test_frozen_startup_runs_current_exe(startup, monkeypatch):
    exe = startup.root / "Shion.exe"
    exe.write_bytes(b"exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert launch_args(startup.root) == [str(exe)]
    startup.set_enabled(True)
    assert startup.inspect() == "enabled"
    assert startup.read() == subprocess.list2cmdline([str(exe)])


def test_registry_error_propagates(startup, monkeypatch):
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(startup.registry, "OpenKey", denied)
    with pytest.raises(PermissionError):
        startup.inspect()
