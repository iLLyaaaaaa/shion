"""测试用：服务端令牌（见 shion/loopback.py）。

正式启动由 shion.server.start_linked 在绑定成功后写令牌。测试里直接起 ShionServer 时，
conftest 的 autouse fixture 会把每个启动的服务端令牌按端口记进 TOKENS，并写进当前 SHION_DATA_DIR
（进程内的 hook 读它）；run_hook 在目标数据目录还没有令牌时按端口补上。
专门测“没有令牌 / 旧令牌”的用例用没登记的端口或先写好的文件，不受影响。
"""
from __future__ import annotations

import os
from pathlib import Path

TOKENS: dict[int, str] = {}  # 本测试里启动过的服务端：端口 → 令牌


def auth(srv) -> dict:
    return {"Authorization": "Bearer " + srv.token}


def auth_port(port) -> dict:
    token = TOKENS.get(int(port))
    return {"Authorization": "Bearer " + token} if token else {}


def link(srv, directory=None) -> dict:
    """把 srv 的令牌写进数据目录（默认当前 SHION_DATA_DIR），返回带令牌的请求头。"""
    from shion.loopback import write_token
    write_token(Path(directory) if directory is not None else Path(os.environ["SHION_DATA_DIR"]), srv.token)
    return auth(srv)


def link_port(port, directory) -> None:
    """目标数据目录还没有令牌时，补上这个端口上服务端的令牌（没登记的端口什么都不做）。"""
    from shion.loopback import read_token, write_token
    token = TOKENS.get(int(port)) if str(port).isdigit() else None
    if token and read_token(Path(directory)) is None:
        write_token(Path(directory), token)
