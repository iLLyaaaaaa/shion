"""tools/check_private.py：只用假名字测试。"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "check_private.py"
spec = importlib.util.spec_from_file_location("check_private", TOOL)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

FAKE_ENV = {"USERNAME": "Zorblax", "COMPUTERNAME": "QUUX-PC-77"}


def test_names_from_env_skips_empty_and_short():
    assert cp.names_from_env(FAKE_ENV) == {"<USERNAME>": "Zorblax", "<COMPUTERNAME>": "QUUX-PC-77"}
    assert cp.names_from_env({"USERNAME": "ab", "COMPUTERNAME": ""}) == {}
    assert cp.names_from_env({}) == {}


def test_find_hits_case_insensitive_masks_name_and_reports_line():
    names = cp.names_from_env(FAKE_ENV)
    files = [
        ("docs/a.md", b"line one\nC:\\Users\\zorblax\\tmp\n"),
        ("ok.txt", b"nothing here"),
        ("bin.dat", b"\x00\x01quux-pc-77\x02"),
    ]
    hits = cp.find_hits(files, names)
    assert [(h.path, h.line, h.label) for h in hits] == [
        ("docs/a.md", 2, "<USERNAME>"),
        ("bin.dat", 1, "<COMPUTERNAME>"),
    ]
    for h in hits:
        assert "zorblax" not in h.excerpt.lower() and "quux-pc-77" not in h.excerpt.lower()
    assert "<USERNAME>" in hits[0].excerpt


def test_find_hits_checks_paths():
    hits = cp.find_hits([("notes/Zorblax-todo.md", b"clean")], cp.names_from_env(FAKE_ENV))
    assert [(h.path, h.line, h.label) for h in hits] == [("notes/<USERNAME>-todo.md", 0, "<USERNAME>")]


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (tmp_path / "clean.txt").write_text("hello\n", encoding="utf-8")
    git("add", "clean.txt")
    git("commit", "-q", "-m", "init")
    return tmp_path, git


def test_main_staged_and_ref(repo, capsys):
    path, git = repo
    assert cp.main([], env=FAKE_ENV, cwd=str(path)) == 0
    assert cp.main(["--ref", "HEAD"], env=FAKE_ENV, cwd=str(path)) == 0

    (path / "leak.md").write_text("tmp: pytest-of-ZORBLAX\n", encoding="utf-8")
    git("add", "leak.md")
    assert cp.main([], env=FAKE_ENV, cwd=str(path)) == 1
    err = capsys.readouterr().err
    assert "leak.md:1" in err and "zorblax" not in err.lower()
    # HEAD 还没有这个文件
    assert cp.main(["--ref", "HEAD"], env=FAKE_ENV, cwd=str(path)) == 0
    git("commit", "-q", "-m", "leak")
    assert cp.main(["--ref", "HEAD"], env=FAKE_ENV, cwd=str(path)) == 1


def test_main_errors(repo, tmp_path_factory):
    path, _ = repo
    assert cp.main([], env={}, cwd=str(path)) == 2
    assert cp.main(["--ref", "no-such-ref"], env=FAKE_ENV, cwd=str(path)) == 2
    assert cp.main([], env=FAKE_ENV, cwd=str(tmp_path_factory.mktemp("not_a_repo"))) == 2
