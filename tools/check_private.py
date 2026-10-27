"""Scan tracked/staged text for local user paths and common credential literals.

Print locations and categories only, never matching secrets. Not a substitute
for a full push-range audit or a dedicated secret scanner.
"""
from pathlib import Path
import re
import subprocess
import sys


def main():
    files = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
    patterns = {
        "personal Windows profile": re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|x\b|<|\{|USER\b)[A-Za-z0-9_.-]+", re.I),
        "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "API credential": re.compile(rb"\b(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}"),
    }
    failures = []
    for filename in filter(None, files):
        path = Path(filename)
        if not path.is_file():
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        for category, pattern in patterns.items():
            if pattern.search(content):
                failures.append(f"{filename}: {category}")
    print("\n".join(failures) if failures else "PASS: tracked files privacy patterns")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
