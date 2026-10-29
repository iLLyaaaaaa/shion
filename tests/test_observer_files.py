"""Native replacement faults must preserve evidence and never weaken checks."""
import ctypes
from ctypes import wintypes
from collections import Counter
from contextlib import contextmanager
import os
import struct
import time

import pytest

from shion import observer_files as S
from tools import codex_config as C

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native file replacement")


def security_permissions(path):
    """Compare permissions without the two Windows-normalized inheritance bits."""
    get = ctypes.WinDLL("advapi32", use_last_error=True).GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID,
                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    get(str(path), 7, None, 0, ctypes.byref(needed))  # owner, group, DACL
    if not 0 < needed.value <= 65536:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not get(str(path), 7, buffer, len(buffer), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    raw = buffer.raw[:needed.value]
    revision, reserved, control, owner, group, sacl, dacl = struct.unpack_from("<BBH4I", raw)
    assert control & 0x8000 and not sacl  # self-relative, no SACL requested

    def sid(offset):
        return raw[offset:offset + 8 + 4 * raw[offset + 1]] if offset else None

    acl = None  # Keep a null DACL distinct from an empty DACL.
    if dacl:
        acl_size, ace_count = struct.unpack_from("<HH", raw, dacl + 2)
        offset, aces = dacl + 8, Counter()
        for _ in range(ace_count):
            ace_type, flags, ace_size = struct.unpack_from("<BBH", raw, offset)
            # Retain the access mask, SID, and any type-specific ACE data,
            # plus every flag except INHERITED_ACE (0x10).
            aces[(ace_type, flags & ~0x10, raw[offset + 4:offset + ace_size])] += 1
            offset += ace_size
        acl = (raw[dacl:dacl + 8], aces, raw[offset:dacl + acl_size])
    # Ignore only SE_DACL_AUTO_INHERITED in descriptor control flags.
    return (revision, reserved, control & ~0x0400, sid(owner), sid(group), acl)


@contextmanager
def held_file(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = create(str(path), 0x80000000, 3, None, 3, 0, None)  # read/write sharing, no delete sharing
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        assert kernel.CloseHandle(handle)


@pytest.mark.parametrize("code", [32, 33, 1175])
def test_retry_only_known_unchanged_state(tmp_path, monkeypatch, code):
    path = tmp_path / "config.toml"
    path.write_bytes(b"old\n")
    security = security_permissions(path)
    # Injected errors use a deterministic retry clock. Real scheduler/FS load
    # may legitimately exhaust the budget before the fourth call; native
    # contention and the expired-budget branch are tested separately below.
    clock = [0.0]
    monkeypatch.setattr(S.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(S.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    native, calls = S._native_replace, []
    def transient(temporary, target):
        calls.append(code)
        if len(calls) < 4:
            raise ctypes.WinError(code)
        return native(temporary, target)
    monkeypatch.setattr(S, "_native_replace", transient)
    start = time.monotonic()
    S.replace_private(path, b"new\n", preserve_security=True)
    assert time.monotonic() - start < .75
    assert len(calls) == 4 and path.read_bytes() == b"new\n"
    assert security_permissions(path) == security
    assert not S.staging_path(path).exists()


def test_retry_exhaustion_keeps_original_and_stage(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(b"original\n")
    calls = []
    clock = [0.0]
    monkeypatch.setattr(S.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(S.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    def fail(*args):
        calls.append(1)
        raise ctypes.WinError(1175)
    monkeypatch.setattr(S, "_native_replace", fail)
    start = time.monotonic()
    with pytest.raises(OSError) as exc:
        S.replace_private(path, b"replacement\n", True)
    assert exc.value.winerror == 1175 and len(calls) == 4
    assert time.monotonic() - start < .75
    assert path.read_bytes() == b"original\n"
    assert S.staging_path(path).read_bytes() == b"replacement\n"


@pytest.mark.parametrize("changed", ["original", "stage", "attributes", "security"])
def test_retry_stops_on_changed_preconditions(tmp_path, monkeypatch, changed):
    path = tmp_path / "config.toml"
    path.write_bytes(b"original\n")
    calls = []
    original_security = S._security_digest
    def fail(temporary, target):
        calls.append(1)
        if changed == "original":
            target.write_bytes(b"external\n")
        elif changed == "stage":
            temporary.write_bytes(b"external\n")
        elif changed == "attributes":
            # Simulate an external metadata change without altering directory ACLs.
            os.utime(target, ns=(1_000_000_000, 1_000_000_000))
        else:
            monkeypatch.setattr(S, "_security_digest", lambda p: b"changed" if p == path else original_security(p))
        raise ctypes.WinError(1175)
    monkeypatch.setattr(S, "_native_replace", fail)
    with pytest.raises(ValueError, match="state changed"):
        S.replace_private(path, b"replacement\n", True)
    assert len(calls) == 1
    assert S.staging_path(path).exists()


@pytest.mark.parametrize("code", [1176, 1177])
def test_nonretryable_partial_native_states_keep_wal_and_images(tmp_path, monkeypatch, code):
    path = tmp_path / "config.toml"
    original = b'notify=["third-party"]\n'
    path.write_bytes(original)
    proposal = C.install_plan(tmp_path, ["C:/Shion/Shion.exe", "--codex-observer"], tmp_path / "data")
    renamed = tmp_path / "native-renamed-original"
    calls = []
    def fail(temporary, target):
        calls.append(1)
        if code == 1176:
            target.unlink()
        else:
            target.rename(renamed)
        raise ctypes.WinError(code)
    monkeypatch.setattr(S, "_native_replace", fail)
    with pytest.raises(C.Conflict, match="External edit"):
        C.apply_plan(proposal)
    assert len(calls) == 1 and not path.exists()
    assert S.staging_path(path).read_bytes() == proposal.changes[0].after
    assert C.transaction_path(tmp_path).exists()
    if code == 1177:
        assert renamed.read_bytes() == original
    with pytest.raises(C.Conflict):
        C.recover(tmp_path)
    assert S.staging_path(path).exists()


@pytest.mark.parametrize("which", ["target", "stage"])
def test_real_handle_without_delete_sharing_is_bounded_and_recoverable(tmp_path, monkeypatch, which):
    path = tmp_path / "config.toml"
    original = b'notify=["keep"]\n'
    path.write_bytes(original)
    security = S._security_digest(path)
    proposal = C.install_plan(tmp_path, ["C:/Shion/Shion.exe", "--codex-observer"], tmp_path / "data")
    native = S._native_replace
    lock, errors = [], []
    def hold_then_replace(temporary, target):
        if not lock:
            context = held_file(target if which == "target" else temporary)
            context.__enter__()
            lock.append(context)
        try:
            return native(temporary, target)
        except OSError as exc:
            errors.append(exc.winerror)
            raise
    monkeypatch.setattr(S, "_native_replace", hold_then_replace)
    try:
        with pytest.raises(OSError):
            C.apply_plan(proposal)
        assert errors and set(errors) <= {32, 33, 1175}
        assert path.read_bytes() == original
        assert S._security_digest(path) == security
    finally:
        for context in lock:
            context.__exit__(None, None, None)
    monkeypatch.setattr(S, "_native_replace", native)
    if C.transaction_path(tmp_path).exists():
        assert C.recover(tmp_path)
    assert not C.recover(tmp_path)
    assert path.read_bytes() == original and not S.staging_path(path).exists()


def test_pre_replace_unexpected_error_is_not_retried(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(b"original")
    calls = []
    def denied(*args):
        calls.append(1)
        raise ctypes.WinError(5)
    monkeypatch.setattr(S, "_native_replace", denied)
    with pytest.raises(OSError) as exc:
        S.replace_private(path, b"replacement", True)
    assert exc.value.winerror == 5 and len(calls) == 1
    assert path.read_bytes() == b"original"


def test_retry_budget_is_checked_again_after_wait(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(b"original")
    now, calls = [0.0], []
    monkeypatch.setattr(S.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(S.time, "sleep", lambda _: now.__setitem__(0, 1.0))
    def fail(*args):
        calls.append(1)
        raise ctypes.WinError(1175)
    monkeypatch.setattr(S, "_native_replace", fail)
    with pytest.raises(OSError) as exc:
        S.replace_private(path, b"replacement", True)
    assert exc.value.winerror == 1175 and len(calls) == 1
    assert path.read_bytes() == b"original"


def test_external_write_during_staging_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_bytes(b"original")
    real_fsync = S.os.fsync
    def external_write(fd):
        real_fsync(fd)
        path.write_bytes(b"external update")
    monkeypatch.setattr(S.os, "fsync", external_write)
    with pytest.raises(ValueError, match="during staging"):
        S.replace_private(path, b"replacement", True, expected=b"original")
    assert path.read_bytes() == b"external update"
    assert S.staging_path(path).read_bytes() == b"replacement"


def test_stale_expected_hash_stops_before_staging(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b"external update")
    with pytest.raises(ValueError, match="before replacement"):
        S.replace_private(path, b"replacement", True, expected=b"old preview")
    assert path.read_bytes() == b"external update"
    assert not S.staging_path(path).exists()
