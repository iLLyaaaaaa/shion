"""Small user-local observer files; inherit directory permissions, no ACL store."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import time


def reject_reparse(path):
    for part in (Path(path), *Path(path).parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 1024):
            raise ValueError("Reparse paths require manual review")


def ensure_directory(path):
    path = Path(path)
    reject_reparse(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_private(path):
    reject_reparse(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("Observer file too large")
    return path.read_bytes()


def write_new(path, content):
    reject_reparse(path)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _security_digest(path):
    """Read-only, in-memory owner/group/DACL fingerprint, never an ACL store."""
    import ctypes
    from ctypes import wintypes
    get = ctypes.WinDLL("advapi32", use_last_error=True).GetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID,
                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    get(str(path), 7, None, 0, ctypes.byref(needed))
    if not 0 < needed.value <= 65536:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not get(str(path), 7, buffer, len(buffer), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return hashlib.sha256(buffer.raw[:needed.value]).digest()


def _state(path, security=False):
    reject_reparse(path)
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
            getattr(stat, "st_file_attributes", 0),
            hashlib.sha256(read_private(path)).digest(),
            _security_digest(path) if security else None)


def _native_replace(temporary, path):
    import ctypes
    from ctypes import wintypes
    replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                        wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    replace.restype = wintypes.BOOL
    if not replace(str(path), str(temporary), None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _replace(temporary, path, preserve_security=False):
    if not (preserve_security and os.name == "nt" and path.exists()):
        os.replace(temporary, path)
        return
    # No ignore-ACL flags or non-atomic fallback. Retry only an unchanged pair.
    original, staged = _state(path, True), _state(temporary)
    deadline = time.monotonic() + .25
    delays = (.01, .03, .06)
    last_error = None
    for attempt in range(4):
        if _state(path, True) != original or _state(temporary) != staged:
            raise ValueError("Replacement state changed; automatic retry stopped")
        if attempt and time.monotonic() >= deadline:
            raise last_error
        try:
            _native_replace(temporary, path)
            return
        except OSError as exc:
            last_error = exc
            # 1176/1177 can rename/remove the original: never retry or guess.
            if (getattr(exc, "winerror", None) not in (32, 33, 1175) or attempt == 3
                    or time.monotonic() + delays[attempt] >= deadline):
                raise
            time.sleep(delays[attempt])


def _existing_state(path, security=False):
    return _state(path, security) if path.exists() else None


def replace_private(path, content, preserve_security=False, expected=...):
    reject_reparse(path)
    ensure_directory(path.parent)
    original = _existing_state(path, preserve_security)
    if expected is not ...:
        expected_hash = hashlib.sha256(expected).digest() if expected is not None else None
        if (original[5] if original else None) != expected_hash:
            raise ValueError("File changed before replacement")
    if content is None:
        if _existing_state(path, preserve_security) != original:
            raise ValueError("File changed before deletion")
        path.unlink(missing_ok=True)
        return
    temporary = staging_path(path)
    reject_reparse(temporary)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if _existing_state(path, preserve_security) != original:
        raise ValueError("File changed during staging; retain transaction evidence")
    # Keep failed/partial staging for WAL validation. In particular 1176/1177
    # must not lose the remaining replacement image in a blanket finally.
    _replace(temporary, path, preserve_security)


def staging_path(path):
    return path.with_name("." + path.name + ".shion-stage")
