"""bundle_smoke 的隔离环境和日志检查（纯函数，不启动 exe）。"""
from pathlib import Path

from tools.bundle_smoke import isolated_environment, log_errors


def test_isolated_environment_does_not_inherit_codex_home_or_observer_port(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "real-codex"))
    monkeypatch.setenv("SHION_OBSERVER_PORT", "47614")
    home = tmp_path / "home"
    env = isolated_environment(home)
    assert Path(env["CODEX_HOME"]) == home / ".codex"
    assert env["SHION_OBSERVER_PORT"] != "47614" and 1024 <= int(env["SHION_OBSERVER_PORT"]) <= 65535
    assert isolated_environment(tmp_path / "home2")["SHION_OBSERVER_PORT"] is not None


def test_log_errors_matches_the_level_field_not_the_message_text():
    info = "2026-11-17 12:00:00,123 shion INFO handled the ERROR response gracefully"
    error = "2026-11-17 12:00:01,456 shion.server ERROR boom"
    critical = "2026-11-17 12:00:02,789 shion CRITICAL bad"
    assert log_errors(info) == []
    assert log_errors("\n".join((info, error, critical, "Traceback (most recent call last):"))) == [
        error, critical, "Traceback (most recent call last):"]
