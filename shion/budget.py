"""Read-only, in-memory Claude Code session token totals."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
import threading
from time import monotonic

from .usage import MAX_LINE, SYNTHETIC, anchor, parse_transcript_line, replaces_usage_record, sha

READ_BUDGET = 0.050
SESSION_TTL = 24 * 60 * 60
MAX_READERS = 4


@dataclass(frozen=True)
class BudgetReading:
    total: int
    main: int
    subagents: int
    complete: bool


@dataclass
class _Cursor:
    identity: tuple[int, int]
    size: int
    modified: int
    offset: int = 0
    tail: bytes = b''
    skipping: bool = False


@dataclass
class _Observation:
    path: Path
    done: threading.Event = field(default_factory=threading.Event)
    reading: BudgetReading | None = None


@dataclass
class _Session:
    last_seen: float
    main_path: Path | None = None
    cursors: dict[Path, _Cursor] = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    totals: list[int] = field(default_factory=lambda: [0, 0])
    pending: _Observation | None = None

    def snapshot(self, complete):
        main, subagents = self.totals
        return BudgetReading(main + subagents, main, subagents, complete)

    def add(self, key, record, source):
        previous = self.records.get(key)
        if previous:
            old_record, old_source, old_total = previous
            if not replaces_usage_record(record, old_record):
                return
            self.totals[old_source] -= old_total
        total = 0 if record['model'] == SYNTHETIC else sum(record['counts'].values())
        self.records[key] = (record, source, total)
        self.totals[source] += total


def _normalized(path):
    return Path(os.path.normcase(path))


def _plain_stat(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError('linked transcript path')
    return info


def _identity(info):
    return info.st_dev, info.st_ino


class BudgetMeter:
    def __init__(self, projects: Path | None = None):
        config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
        self._projects = Path(projects) if projects is not None else config / 'projects'
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.Lock()
        self._readers = threading.BoundedSemaphore(MAX_READERS)

    def observe(self, session_id: str, transcript_path: str | Path) -> BudgetReading | None:
        """Return the cumulative reading, a partial reading on timeout, or None on failure."""
        now = monotonic()
        deadline = now + READ_BUDGET
        try:
            if not isinstance(session_id, str) or not session_id or any(c in session_id for c in '/\\:'):
                return None
            path = Path(transcript_path)
            if (not path.is_absolute() or '..' in path.parts
                    or os.path.normcase(path.name) != os.path.normcase(f'{session_id}.jsonl')):
                return None
            if not self._lock.acquire(timeout=max(0, deadline - monotonic())):
                return None
            try:
                # A timed-out worker owns its old state object. Eviction detaches it.
                while self._sessions and now - next(iter(self._sessions.values())).last_seen > SESSION_TTL:
                    self._sessions.popitem(last=False)
                    if monotonic() >= deadline:
                        return None
                session = self._sessions.get(session_id)
                if session is not None:
                    session.last_seen = monotonic()
                    self._sessions.move_to_end(session_id)
                observation = session.pending if session is not None else None
                start_reader = observation is None
                if start_reader:
                    if monotonic() >= deadline or not self._readers.acquire(blocking=False):
                        return None
                    if session is None:
                        session = self._sessions[session_id] = _Session(monotonic())
                    observation = session.pending = _Observation(path)
                elif observation.path != path:
                    return None  # Never share a result for a different requested path.
            finally:
                self._lock.release()
            if start_reader:
                try:
                    threading.Thread(target=self._observe, args=(session, path, observation, deadline),
                                     name='shion-budget', daemon=True).start()
                except Exception:
                    self._finish(session, observation)
                    return None
            observation.done.wait(max(0, deadline - monotonic()))
            return observation.reading
        except Exception:
            return None

    def _finish(self, session, observation):
        with self._lock:
            session.pending = None
            self._readers.release()
        observation.done.set()

    def _observe(self, session, path, observation, deadline):
        try:
            self._read(session, path, observation, deadline)
        except Exception:
            observation.reading = None
        finally:
            self._finish(session, observation)

    def _validated(self, path, projects, *, directory=False):
        # Check the supplied components before resolve can hide a link or junction.
        relative = _normalized(path).relative_to(_normalized(self._projects.absolute()))
        if not relative.parts or any(':' in part for part in relative.parts):
            raise ValueError('expected a path below projects')
        for parent in reversed(path.parents):
            _plain_stat(parent)
        info = _plain_stat(path)
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        if not kind(info.st_mode):
            raise ValueError('unexpected transcript file type')
        resolved = path.resolve(strict=True)
        _normalized(resolved).relative_to(projects)
        return resolved, info

    def _paths(self, main, projects):
        directory = main.with_suffix('') / 'subagents'
        try:
            _plain_stat(directory.parent)
            directory, _ = self._validated(directory, projects, directory=True)
        except FileNotFoundError:
            return
        yield from sorted(child for child in directory.iterdir() if child.match('*.jsonl'))

    def _open(self, path, info):
        stream = path.open('rb')
        try:
            # Check the opened file as well, in case its pathname changed after validation.
            if _identity(os.fstat(stream.fileno())) != _identity(info) or _identity(_plain_stat(path)) != _identity(info):
                raise ValueError('transcript changed while opening')
            return stream
        except Exception:
            stream.close()
            raise

    def _changed(self, paths, session, observation, deadline):
        if session.cursors.keys() - paths.keys():
            return True
        for file, cursor in session.cursors.items():
            info = paths[file]
            if (cursor.identity != _identity(info) or info.st_size < cursor.size
                    or (info.st_size == cursor.size and info.st_mtime_ns != cursor.modified)):
                return True
        observation.reading = session.snapshot(False)
        for file, cursor in session.cursors.items():
            if monotonic() >= deadline:
                break
            with self._open(file, paths[file]) as stream:
                if anchor(stream, cursor.offset) != sha(cursor.tail):
                    return True
        return False

    def _read(self, session, path, observation, deadline):
        projects = _normalized(self._projects.resolve(strict=True))
        main, info = self._validated(path, projects)
        observation.reading = BudgetReading(0, 0, 0, False)
        if monotonic() >= deadline:
            return
        paths = {main: info}
        for child in self._paths(main, projects):
            if monotonic() >= deadline:
                return
            child, info = self._validated(child, projects)
            paths[child] = info
        if session.main_path != main or self._changed(paths, session, observation, deadline):
            session.main_path = main
            session.cursors.clear()
            session.records.clear()
            session.totals[:] = (0, 0)
        observation.reading = session.snapshot(False)
        for file in sorted(paths):
            if monotonic() >= deadline:
                return
            info = paths[file]
            cursor = session.cursors.get(file)
            if cursor is None:
                cursor = session.cursors[file] = _Cursor(_identity(info), info.st_size, info.st_mtime_ns)
            with self._open(file, info) as stream:
                cursor.size, cursor.modified = info.st_size, info.st_mtime_ns
                if not self._read_file(stream, cursor, session, int(file != main), observation, deadline):
                    return
        observation.reading = session.snapshot(True)

    @staticmethod
    def _read_file(stream, cursor, session, source, observation, deadline):
        stream.seek(cursor.offset)
        while cursor.offset < cursor.size:
            if monotonic() >= deadline:
                return False
            chunk = stream.readline(min(MAX_LINE + 1, cursor.size - cursor.offset))
            if monotonic() >= deadline:
                return False
            if not chunk:
                raise OSError('transcript shortened while reading')
            complete = chunk.endswith(b'\n')
            if not complete and len(chunk) <= MAX_LINE and not cursor.skipping:
                break  # The next checkpoint can see the rest of this line.
            if complete and len(chunk) <= MAX_LINE and not cursor.skipping:
                _, key, record, _ = parse_transcript_line(chunk)
                if monotonic() >= deadline:
                    return False
                if record is not None:
                    session.add(key, record, source)
            cursor.offset += len(chunk)
            cursor.tail = (cursor.tail + chunk[-256:])[-256:]
            cursor.skipping = not complete
            observation.reading = session.snapshot(False)
        return True
