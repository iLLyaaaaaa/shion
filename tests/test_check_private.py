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
        ("docs/a.md", b"line one\nC:" + b"\\Users\\zorblax\\tmp\n"),
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


def test_main_errors(repo, tmp_path_factory, monkeypatch):
    path, _ = repo
    assert cp.main([], env={}, cwd=str(path)) == 2
    assert cp.main(["--ref", "no-such-ref"], env=FAKE_ENV, cwd=str(path)) == 2
    not_repo = tmp_path_factory.mktemp("not_a_repo")
    # basetemp is inside this checkout; prevent Git discovering its parent repo.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(not_repo.parent))
    assert cp.main([], env=FAKE_ENV, cwd=str(not_repo)) == 2


EXTRA_CASES = [
    ("personal Windows profile", b"C:" + b"\\Users\\SyntheticPerson\\notes.txt"),
    ("private key", b"-----BEGIN " + b"PRIVATE KEY-----\nsynthetic body"),
    ("API credential", b"ghp_" + b"a" * 24),
]


@pytest.mark.parametrize("label,payload", EXTRA_CASES)
def test_extra_categories_read_index_and_ref_instead_of_worktree(repo, capsys, label, payload):
    path, git = repo
    leak = path / "leak.txt"
    leak.write_bytes(b"safe\n" + payload)
    git("add", "leak.txt")
    leak.write_bytes(b"working tree is clean")
    assert cp.main([], env=FAKE_ENV, cwd=str(path)) == 1
    err = capsys.readouterr().err
    assert "leak.txt:2" in err and label in err
    assert payload.decode() not in err  # Never echo the content, including its secret.
    assert cp.main(["--ref", "HEAD"], env=FAKE_ENV, cwd=str(path)) == 0
    git("commit", "-q", "-m", "synthetic fixture")
    git("add", "leak.txt")  # Now index is clean, committed snapshot still contains it.
    assert cp.main([], env=FAKE_ENV, cwd=str(path)) == 0
    assert cp.main(["--ref", "HEAD"], env=FAKE_ENV, cwd=str(path)) == 1
    err = capsys.readouterr().err
    assert label in err and payload.decode() not in err


@pytest.mark.parametrize("label,payload", EXTRA_CASES)
def test_extra_categories_check_and_redact_paths(label, payload):
    private_path = payload.split(b"\n")[0].decode() + "/fixture.txt"
    hits = cp.scan_files([(private_path, b"clean")], cp.names_from_env(FAKE_ENV))
    assert [(h.line, h.label) for h in hits] == [(0, label)]
    assert payload.split(b"\n")[0].decode() not in hits[0].path
    assert hits[0].excerpt == ""


@pytest.mark.parametrize("prefix", [b"sk-proj-", b"ghp_", b"github_pat_"])
def test_all_v2_api_prefixes_are_detected_in_binary_content(prefix):
    hits = cp.scan_files([("binary.dat", b"\0" + prefix + b"z" * 24)], cp.names_from_env(FAKE_ENV))
    assert [(h.path, h.line, h.label) for h in hits] == [("binary.dat", 1, "API credential")]


@pytest.mark.parametrize("kind", [b"", b"RSA ", b"EC ", b"OPENSSH "])
def test_all_v2_private_key_headers_are_detected(kind):
    header = b"-----BEGIN " + kind + b"PRIVATE KEY-----"
    assert cp.scan_files([("fixture.pem", header)], cp.names_from_env(FAKE_ENV))[0].label == "private key"


@pytest.mark.parametrize("placeholder", ["Public", "Default", "x", "USER", "<user>", "{user}"])
def test_profile_placeholders_do_not_trigger_extra_category(placeholder):
    value = "C:" + "/Users/" + placeholder + "/fixture.txt"
    assert not cp.scan_files([("fixture.txt", value.encode())], cp.names_from_env(FAKE_ENV))


def test_name_hit_on_secret_line_and_secret_filename_never_echo_secret(repo, capsys):
    path, git = repo
    secret = "ghp_" + "Zorblax" + "b" * 24  # Name overlaps a credential.
    (path / (secret + ".txt")).write_text("ZORBLAX " + secret, encoding="utf-8")
    git("add", secret + ".txt")
    assert cp.main([], env=FAKE_ENV, cwd=str(path)) == 1
    output = capsys.readouterr()
    assert secret not in output.err and "zorblax" not in output.err.lower()
    assert "<USERNAME>" in output.err and "API credential" in output.err
    assert "b" * 24 not in output.err
