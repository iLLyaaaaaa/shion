"""本机回环服务的公共安全代码（只用标准库，hook 也会 import）。

- 令牌文件：诗音每次启动生成新令牌，47613 绑定成功后才写进数据目录；hook 读到令牌才发请求，
  服务端只认带对令牌的请求。端口被别的进程占住时不写文件，hook 就不会去连冒充者。
- 独占绑定：Windows 上设 SO_EXCLUSIVEADDRUSE，绑上以后别的 socket 不能再绑同一端口抢连接。
"""
from __future__ import annotations

import json
import os
import secrets
import socket
from pathlib import Path
from typing import Optional

TOKEN_FILE = "claude-link.json"
TOKEN_LEN = 64
_HEX = frozenset("0123456789abcdef")


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


def read_token(directory: Optional[Path] = None) -> Optional[str]:
    """读令牌；文件不存在、过大、是重解析点或内容不对都返回 None。"""
    try:
        from shion import observer_files as secure
        path = token_path(default_data_dir() if directory is None else directory)
        data = json.loads(secure.read_private(path))
        token = data.get("token") if isinstance(data, dict) else None
        return token if valid_token(token) else None
    except Exception:
        return None


def write_token(directory: Path, token: str) -> None:
    from shion import observer_files as secure
    if not valid_token(token):
        raise ValueError("invalid token")
    path = token_path(directory)
    secure.ensure_directory(path.parent)
    stage = secure.staging_path(path)
    secure.reject_reparse(stage)
    stage.unlink(missing_ok=True)  # 上次崩溃留下的暂存文件：令牌没有事务要恢复，直接丢掉
    secure.replace_private(path, json.dumps({"token": token}).encode("utf-8"))


def remove_token(directory: Path) -> None:
    """删掉令牌文件；不存在或删不掉都不报错（删不掉的旧令牌也对不上新服务端）。"""
    try:
        from shion import observer_files as secure
        path = token_path(directory)
        secure.reject_reparse(path)
        path.unlink(missing_ok=True)
    except Exception:
        pass


def bind_exclusive(sock: socket.socket, address) -> None:
    """绑定前在 Windows 上设 SO_EXCLUSIVEADDRUSE（不设 SO_REUSEADDR）。"""
    option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if os.name == "nt" and option is not None:
        sock.setsockopt(socket.SOL_SOCKET, option, 1)
    sock.bind(address)
