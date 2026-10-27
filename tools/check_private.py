"""检查仓库内容里有没有本机的真实用户名 / 机器名。只用标准库。

名字在运行时从环境变量 USERNAME、COMPUTERNAME 读取，脚本里不写任何真实名字。
不区分大小写；文件路径和文件内容都查。输出里名字用 <USERNAME> 这样的占位代替。

用法：
    python tools/check_private.py            # 扫描暂存区（索引）里的全部文件，适合 pre-commit
    python tools/check_private.py --ref HEAD # 扫描某个提交 / 分支 / 标签里的全部文件
退出码：0 没命中；1 有命中；2 出错（例如读不到名字、不在 git 仓库里）。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Iterable, Iterator, Mapping, NamedTuple

ENV_VARS = ("USERNAME", "COMPUTERNAME")
MIN_LEN = 3  # 太短的名字会到处误报，跳过并提示


class Hit(NamedTuple):
    path: str
    line: int  # 0 表示命中在文件路径里
    label: str
    excerpt: str


def names_from_env(env: Mapping[str, str]) -> dict[str, str]:
    """返回 {占位标签: 名字}。空值和过短的名字跳过。"""
    names = {}
    for var in ENV_VARS:
        value = (env.get(var) or "").strip()
        if len(value) >= MIN_LEN:
            names[f"<{var}>"] = value
    return names


def _patterns(names: Mapping[str, str]) -> list[tuple[str, re.Pattern[bytes]]]:
    return [(label, re.compile(re.escape(name.encode("utf-8")), re.I)) for label, name in names.items()]


def _mask(text: bytes, patterns) -> str:
    for label, pat in patterns:
        text = pat.sub(label.encode(), text)
    return text.decode("utf-8", "replace").strip()[:120]


def find_hits(files: Iterable[tuple[str, bytes]], names: Mapping[str, str]) -> list[Hit]:
    patterns = _patterns(names)
    hits: list[Hit] = []
    for path, data in files:
        shown = _mask(path.encode("utf-8"), patterns)
        for label, pat in patterns:
            if pat.search(path.encode("utf-8")):
                hits.append(Hit(shown, 0, label, "(文件路径)"))
        if not any(pat.search(data) for _, pat in patterns):
            continue
        for no, line in enumerate(data.split(b"\n"), 1):
            for label, pat in patterns:
                if pat.search(line):
                    hits.append(Hit(shown, no, label, _mask(line, patterns)))
    return hits


def _git(args: list[str], cwd: str | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout


def _entries(ref: str | None, cwd: str | None) -> list[tuple[str, str]]:
    """[(blob id, 路径)]；ref 为 None 时读索引。子模块（commit 类型）跳过。"""
    if ref is None:
        raw = _git(["ls-files", "-s", "-z"], cwd)
        out = []
        for item in raw.split(b"\0"):
            if not item:
                continue
            meta, path = item.split(b"\t", 1)
            mode, oid, _stage = meta.split()
            if mode != b"160000":
                out.append((oid.decode(), path.decode("utf-8", "replace")))
        return out
    raw = _git(["ls-tree", "-r", "-z", "--full-tree", ref], cwd)
    out = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        _mode, kind, oid = meta.split()
        if kind == b"blob":
            out.append((oid.decode(), path.decode("utf-8", "replace")))
    return out


def iter_files(ref: str | None = None, cwd: str | None = None) -> Iterator[tuple[str, bytes]]:
    entries = _entries(ref, cwd)
    if not entries:
        return
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin and proc.stdout
    try:
        for oid, path in entries:
            proc.stdin.write(oid.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)  # 结尾换行
            yield path, data
    finally:
        proc.stdin.close()
        proc.wait()


def _utf8_when_piped() -> None:
    """git hook 等场景输出被管道接走时，按 UTF-8 写，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, cwd: str | None = None) -> int:
    _utf8_when_piped()
    parser = argparse.ArgumentParser(description="检查仓库内容里有没有本机用户名 / 机器名")
    parser.add_argument("--ref", help="扫描这个提交 / 分支 / 标签的全部文件；不填则扫描暂存区")
    args = parser.parse_args(argv)
    names = names_from_env(os.environ if env is None else env)
    if not names:
        print(f"check_private: 读不到 {' / '.join(ENV_VARS)}（或都短于 {MIN_LEN} 个字符），无法检查", file=sys.stderr)
        return 2
    try:
        hits = find_hits(iter_files(args.ref, cwd), names)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"check_private: 调用 git 失败：{exc}", file=sys.stderr)
        return 2
    where = f"ref {args.ref}" if args.ref else "暂存区"
    if not hits:
        print(f"check_private: {where} 中没有发现 {'、'.join(names)}")
        return 0
    print(f"check_private: {where} 中发现 {len(hits)} 处本机名字：", file=sys.stderr)
    for hit in hits:
        loc = hit.path if hit.line == 0 else f"{hit.path}:{hit.line}"
        print(f"  {loc}  {hit.label}  {hit.excerpt}", file=sys.stderr)
    print("请把它们换成 <user> 之类的占位再提交。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
