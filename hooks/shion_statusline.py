"""Fail-open statusLine relay. Standard library only; never opens transcripts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

CACHE_NAME = 'statusline-last.bin'
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def payload(raw):
    from shion.limits import parse_limits, WINDOWS
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Invalid input')
    limits = data.get('rate_limits')
    result = {'session': data.get('session_id')}
    if isinstance(limits, dict):
        for key in WINDOWS:
            value = limits.get(key)
            if isinstance(value, dict):
                candidate = {k: value.get(k) for k in ('used_percentage', 'resets_at')}
                try:
                    parse_limits({'session': result['session'], key: candidate})
                except ValueError:
                    continue
                result[key] = candidate
    return parse_limits(result)


def forward(raw):
    try:
        from hooks.shion_hook import request
        request('/usage/limits', payload(raw), timeout=0.3)
    except Exception:
        pass


def cache_path():
    directory = os.environ.get('SHION_DATA_DIR')
    return (Path(directory) if directory else Path(os.environ['APPDATA']) / 'Shion') / CACHE_NAME


def read_cache():
    try:
        return cache_path().read_bytes()
    except Exception:
        return b''


def write_cache(output):
    # Local only; atomic so a concurrent reader never sees a partial line.
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
        tmp.write_bytes(output)
        os.replace(tmp, path)
    except Exception:
        pass


def run_original(record):
    saved = json.loads(Path(record).read_text(encoding='utf-8'))
    if saved.get('version') != 1 or saved.get('original_raw') is None:
        return None
    original = json.loads(saved['original_raw'])
    if not isinstance(original, dict) or original.get('type') != 'command':
        return None
    command = original.get('command')
    if not isinstance(command, str) or not command:
        return None
    return command


def chain(raw, record):
    """Run the user's original command; on success cache its output, on timeout/failure replay the cache."""
    try:
        command = run_original(record)
        if command is None:
            return b''
        # It is the user's original shell command, not text derived from stdin.
        from tools.hooks_config import statusline_shell
        proc = subprocess.Popen([*statusline_shell(), command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            output = proc.communicate(raw, timeout=1)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            # Descendants can retain pipe handles. Never wait for EOF here.
            threading.Thread(target=proc.communicate, daemon=True).start()
            return read_cache()
        if proc.returncode == 0 and output:
            write_cache(output)
            return output
        return read_cache()
    except Exception:
        return read_cache()


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--record', required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read()
        worker = threading.Thread(target=forward, args=(raw,), daemon=True)
        worker.start()
        output = chain(raw, args.record)
        if output:
            sys.stdout.buffer.write(output)
            sys.stdout.buffer.flush()
        worker.join(0.35)
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    os._exit(main())
