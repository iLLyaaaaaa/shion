"""本机回环服务的公共安全代码（只用标准库，hook 也会 import）。

- 令牌文件：诗音每次启动生成新令牌，47613 绑定成功后才写进数据目录，连同诗音自己的进程号和启动时间；
  hook 读到令牌、并核对那个诗音进程还活着（进程号和启动时间都对得上）才发请求，服务端只认带对令牌的请求。
  端口被别的进程占住时不写文件；诗音崩溃留下的旧令牌对应的进程已经不在，hook 也不会用它。
- 只检查最后两层（数据目录本身、令牌文件本身）是不是重解析点：上级目录别的账户改不了，
  用 junction 搬过家的用户目录也能正常用。
- 独占绑定：Windows 上设 SO_EXCLUSIVEADDRUSE，绑上以后别的 socket 不能再绑同一端口抢连接。
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import stat
from pathlib import Path
from typing import Callable, Optional

TOKEN_FILE = "claude-link.json"
TOKEN_LEN = 64
MAX_FILE = 4096
_HEX = frozenset("0123456789abcdef")
_REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def default_data_dir() -> Path:
    """和 shion/app.py:data_dir()、hook 的 read_save 同一规则：SHION_DATA_DIR 优先，否则 %APPDATA%/Shion。"""
    directory = os.environ.get("SHION_DATA_DIR")
    return Path(directory) if directory else Path(os.environ["APPDATA"]) / "Shion"


def new_token() -> str:
    return secrets.token_hex(TOKEN_LEN // 2)


def valid_token(value) -> bool:
    return isinstance(value, str) and len(value) == TOKEN_LEN and set(value) <= _HEX


def token_path(directory: Path) -> Path:
    return Path(directory) / TOKEN_FILE


def _is_reparse(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _check_last_two(directory: Path) -> Path:
    path = token_path(directory)
    if _is_reparse(Path(directory)) or _is_reparse(path):
        raise ValueError("token path is a reparse point")
    return path


def _process_created(pid: int) -> Optional[int]:
    try:
        from shion import winproc  # 只用标准库 ctypes
        return winproc.process_created(pid)
    except Exception:
        return None


def read_record(directory: Optional[Path] = None) -> Optional[dict]:
    """令牌文件内容 {"token", "pid", "created"}；不存在、过大、是重解析点或格式不对返回 None。只校验格式。"""
    try:
        path = _check_last_two(default_data_dir() if directory is None else Path(directory))
        with open(path, "rb") as stream:
            raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or not valid_token(data.get("token")):
            return None
        return data
    except Exception:
        return None


def read_token(directory: Optional[Path] = None) -> Optional[str]:
    """只按格式读出令牌（不核对诗音进程）；测试和诊断用。hook 用 read_link。"""
    record = read_record(directory)
    return record["token"] if record else None


def _process_running(pid: int, created: int) -> bool:
    try:
        from shion import winproc  # 只用标准库 ctypes
        return winproc.process_running(pid, created)
    except Exception:
        return False


def read_link(directory: Optional[Path] = None,
              running: Callable[[int, int], bool] = _process_running) -> Optional[str]:
    """hook 用：令牌格式正确、而且写它的诗音进程还在运行（进程号、启动时间对得上且没退出）才返回令牌。

    诗音崩溃 / 被强制结束后留下的旧令牌对应的进程已经退出（或 PID 被别的进程复用、启动时间不同），返回 None。
    非 Windows 上拿不到进程启动时间，只校验格式。
    """
    record = read_record(directory)
    if record is None:
        return None
    if os.name != "nt":
        return record["token"]
    pid, created = record.get("pid"), record.get("created")
    if (type(pid) is not int or pid <= 0 or type(created) is not int or created <= 0
            or not running(pid, created)):
        return None
    return record["token"]


def write_token(directory: Path, token: str, pid: Optional[int] = None, created: Optional[int] = None) -> None:
    """原子写入令牌和写入者（默认本进程）的进程号、启动时间。目录本身或令牌文件是重解析点时拒绝。"""
    if not valid_token(token):
        raise ValueError("invalid token")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = _check_last_two(directory)
    pid = os.getpid() if pid is None else pid
    created = _process_created(pid) if created is None else created
    if os.name == "nt" and type(created) is not int:
        raise OSError("cannot read the process start time")  # hook 会核对它；写进去也用不了
    content = json.dumps({"token": token, "pid": pid, "created": created}).encode("utf-8")
    temporary = directory / f".{TOKEN_FILE}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _check_last_two(directory)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def remove_token(directory: Path) -> None:
    """删掉令牌文件；不存在、是重解析点或删不掉都不报错（旧令牌也过不了 read_link 的进程核对）。"""
    try:
        path = _check_last_two(Path(directory))
        path.unlink(missing_ok=True)
    except Exception:
        pass


def bind_exclusive(sock: socket.socket, address) -> None:
    """绑定前在 Windows 上设 SO_EXCLUSIVEADDRUSE（不设 SO_REUSEADDR）。"""
    option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if os.name == "nt" and option is not None:
        sock.setsockopt(socket.SOL_SOCKET, option, 1)
    sock.bind(address)
