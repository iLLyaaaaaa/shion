"""Small user-local observer files; inherit directory permissions, no ACL store."""
from __future__ import annotations

import os
from pathlib import Path


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


def _replace(temporary, path, preserve_security=False):
    if preserve_security and os.name == "nt" and path.exists():
        # Native replacement preserves the existing file DACL. This is not a
        # separate ACL store and never grants access or repairs permissions.
        import ctypes
        from ctypes import wintypes
        replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
        replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
        replace.restype = wintypes.BOOL
        if not replace(str(path), str(temporary), None, 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(temporary, path)


def replace_private(path, content, preserve_security=False):
    reject_reparse(path)
    ensure_directory(path.parent)
    if content is None:
        path.unlink(missing_ok=True)
        return
    temporary = staging_path(path)
    reject_reparse(temporary)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path, preserve_security)
    finally:
        temporary.unlink(missing_ok=True)


def staging_path(path):
    return path.with_name("." + path.name + ".shion-stage")
