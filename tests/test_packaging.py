"""打包后会失去 Python 命令和控制台，覆盖这些运行差异。"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shion import runtime

ROOT = Path(__file__).resolve().parent.parent


def test_existing_standard_streams_are_preserved():
    before = (sys.stdin, sys.stdout, sys.stderr)
    runtime.prepare_standard_streams()
    assert (sys.stdin, sys.stdout, sys.stderr) == before


def test_missing_standard_handles_have_binary_capable_null_streams(monkeypatch):
    def unavailable(*args):
        raise OSError("no pipe")

    monkeypatch.setattr(runtime, "_windows_stream", unavailable)
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, name, None)
    runtime.prepare_standard_streams()
    try:
        assert sys.stdin.buffer.read() == b""
        sys.stdout.buffer.write("诗音".encode("utf-8"))
        sys.stderr.write("test")
        sys.stdout.flush()
    finally:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            stream.close()


def test_frozen_existing_text_streams_use_utf8(monkeypatch):
    calls = []
    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, name, Stream())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    runtime.prepare_standard_streams()
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 3


@pytest.mark.skipif(os.name != "nt", reason="Windows inherited pipe handles")
def test_windowed_missing_streams_restore_utf8_pipes(tmp_path):
    code = f"""
import ctypes, json, sys
sys.path.insert(0, {str(ROOT)!r})
from shion.runtime import prepare_standard_streams
sys.stdin = sys.stdout = sys.stderr = None
prepare_standard_streams()
value = json.loads(sys.stdin.buffer.read().decode('utf-8'))
sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode('utf-8'))
sys.stdout.flush()
assert not ctypes.windll.kernel32.GetConsoleWindow()
"""
    payload = {"session_id": "临时会话", "message": "继续加油"}
    result = subprocess.run([str(Path(sys.executable).with_name("pythonw.exe")), "-c", code],
                            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            capture_output=True, timeout=15, cwd=tmp_path)
    assert result.returncode == 0 and result.stderr == b""
    assert json.loads(result.stdout) == payload


def test_frozen_helpers_use_current_exe_and_protect_hook_image(tmp_path, monkeypatch):
    exe = tmp_path / "诗音 with spaces" / "Shion.exe"
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime.console_send_command(12, 34, "继续") == [
        str(exe), "--console-send", "--pid", "12", "--created", "34", "--text", "继续"]
    assert runtime.hook_process_images(ROOT) == (str(exe),)
    from shion.interrupt import CCProcess, ProcessView, tool_processes
    # 两个工具执行期启动的直接子进程；exe hook 不能被当作工具进程。
    table = {1: (0, "claude.exe"), 2: (1, "Shion.exe"), 3: (1, "tool.exe")}
    view = ProcessView(created=lambda pid: 116444736000000000 + 1000 * 10**7,
                       image=lambda pid: str(exe) if pid == 2 else "tool.exe")
    assert tool_processes(CCProcess(1, 1, "claude.exe", "cli"), [999], view, table,
                          runtime.hook_process_images(ROOT)) == [3]


def test_source_helpers_keep_python_module_command(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert runtime.console_send_command(1, 2, "Continue")[1:3] == ["-m", "shion.console_send"]
    assert runtime.hook_process_images(ROOT) == (str(ROOT / ".venv/Scripts/python.exe"),)


@pytest.mark.parametrize("args,expected", [
    (["--hook", "Stop"], 0),
    (["--console-send", "--pid", "0", "--created", "0", "--text", "Continue"], 1),
])
def test_helper_dispatch_does_not_import_qt(args, expected, tmp_path):
    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from shion.__main__ import main
result = main({args!r})
assert not any(key.startswith('PySide6.Qt') for key in sys.modules)
sys.exit(result)
"""
    result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "SHION_PORT": "1"},
                            input=b"{}", capture_output=True, timeout=15, cwd=tmp_path)
    assert result.returncode == expected, result.stderr.decode("utf-8", "replace")
    if args[0] == "--console-send":
        assert json.loads(result.stdout) == {"ok": False, "reason": "gone"}


def test_default_data_dir_obeys_appdata_without_qt_known_folder(monkeypatch, tmp_path):
    from shion.app import data_dir
    monkeypatch.delenv("SHION_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert data_dir() == tmp_path / "Roaming" / "Shion"
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path / "override"))
    assert data_dir() == tmp_path / "override"


def test_connection_self_check_rejects_source_before_writing(tmp_path):
    from shion.bundle_check import check_connection
    with pytest.raises(ValueError, match="冻结程序"):
        check_connection(str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_connection_self_check_rejects_mismatched_home_before_writing(tmp_path, monkeypatch):
    from shion.bundle_check import check_connection
    import tempfile
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path.parent))
    with pytest.raises(ValueError, match="HOME"):
        check_connection(str(tmp_path))
    assert not list(tmp_path.iterdir())


def test_build_search_path_does_not_inherit_foreign_dlls(monkeypatch):
    from tools.build import build_environment
    monkeypatch.setenv("PATH", r"C:\foreign-app\bin")
    monkeypatch.setenv("QT_PLUGIN_PATH", r"C:\foreign-qt\plugins")
    monkeypatch.setenv("PYTHONPATH", r"C:\foreign-python")
    result = build_environment()
    assert "foreign" not in result["PATH"]
    assert "QT_PLUGIN_PATH" not in result and "PYTHONPATH" not in result
    assert str(Path(sys.executable).parent) in result["PATH"]
