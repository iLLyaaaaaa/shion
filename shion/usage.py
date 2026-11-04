"""Private, read-only transcript metadata aggregation. No Qt or network access."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('in', 'out', 'cw5', 'cw1', 'cr')
MAX_LINE = 1024 * 1024
CACHE_VERSION = 2  # 2: <synthetic> is kept apart from <unknown>.
SYNTHETIC = '<synthetic>'


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Pricing:
    def __init__(self, data=None):
        try:
            raw = data if data is not None else json.loads((ROOT / 'assets/pricing.json').read_text(encoding='utf-8'))
            valid = []
            for item in raw['models']:
                if (not item['prefixes'] or any(not isinstance(p, str) or not re.fullmatch(r'claude-[a-z0-9-]+', p)
                                               for p in item['prefixes'])):
                    raise ValueError()
                thresholds = [t['above_input_tokens'] for t in item['tiers']]
                if (0 not in thresholds or len(set(thresholds)) != len(thresholds)
                        or any(type(t) is not int or t < 0 for t in thresholds)):
                    raise ValueError()
                for tier in item['tiers']:
                    if (set(tier['rates']) != set(FIELDS) or any(type(v) not in (float, int) or
                            not math.isfinite(v) or v < 0 for v in tier['rates'].values())):
                        raise ValueError()
                valid.append(item)
            self.data = {**raw, 'models': valid}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            self.data = {'models': []}  # An invalid editable table must not prevent startup.

    def model(self, model):
        candidates = [(len(prefix), item) for item in self.data['models'] for prefix in item['prefixes']
                      if model == prefix or re.fullmatch(re.escape(prefix) + r'-(?:[0-9]{8}|latest)', model)]
        return max(candidates, key=lambda pair: pair[0])[1] if candidates else None

    def tier(self, model, tokens):
        item = self.model(model)
        thresholds = [t['above_input_tokens'] for t in item['tiers']] if item else [0]
        return str(max(t for t in thresholds if t == 0 or tokens > t))

    def estimate(self, days):
        amount, partial = 0.0, False
        for models in days.values():
            for model, tiers in models.items():
                item = self.model(model)
                for threshold, counts in tiers.items():
                    # Client-generated and empty rows cost nothing; never mark them unpriced.
                    if model == SYNTHETIC or not any(counts.get(k, 0) for k in FIELDS):
                        continue
                    tier = next((t for t in item['tiers'] if str(t['above_input_tokens']) == threshold), None) if item else None
                    if tier is None:
                        partial = True
                    else:
                        amount += sum(counts.get(k, 0) * tier['rates'][k] for k in FIELDS) / 1_000_000
        return amount, partial

    def signature(self):
        # Rate edits never invalidate token aggregates; threshold edits do.
        return sha(json.dumps([(i['prefixes'], [t['above_input_tokens'] for t in i['tiers']])
                               for i in self.data['models']], sort_keys=True).encode())


def metadata(pairs):
    allowed = {'type', 'timestamp', 'message', 'id', 'requestId', 'model', 'usage',
               'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens',
               'cache_creation', 'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}
    return {k: v for k, v in pairs if k in allowed}


def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone() if dt.tzinfo is not None else None
    except (AttributeError, ValueError, OverflowError, OSError):
        return None


def model_name(value):
    # Retain safe unknown model identifiers for partial-pricing reports.
    if value == SYNTHETIC:
        return value
    return value if isinstance(value, str) and re.fullmatch(r'claude-[a-z0-9-]{1,80}', value) else '<unknown>'


def counts_from(usage):
    values = [usage.get(k, 0) for k in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')]
    if any(type(v) is not int or v < 0 for v in values):
        return None
    inp, out, cw, cr = values
    split = usage.get('cache_creation')
    cw5, cw1 = cw, 0
    if isinstance(split, dict):
        five, hour = split.get('ephemeral_5m_input_tokens', 0), split.get('ephemeral_1h_input_tokens', 0)
        if any(type(v) is not int or v < 0 for v in (five, hour)) or five + hour > cw:
            return None
        cw5, cw1 = cw - hour, hour  # Any unspecified remainder uses 5m.
    return dict(zip(FIELDS, (inp, out, cw5, cw1, cr)))


def empty(signature):
    return {'version': CACHE_VERSION, 'pricing_shape': signature, 'days': {}, 'activity': {}, 'files': {}, 'seen': {}}


def load_cache(path, signature):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['version'] != CACHE_VERSION or data['pricing_shape'] != signature:
            raise ValueError()
        # Reject unexpected shapes; malformed caches trigger a clean rebuild.
        for key in ('days', 'activity', 'files', 'seen'):
            if not isinstance(data[key], dict):
                raise ValueError()
        for day, models in data['days'].items():
            date.fromisoformat(day)
            for model, tiers in models.items():
                if model_name(model) != model and model != '<unknown>':
                    raise ValueError()
                for tier, counts in tiers.items():
                    int(tier)
                    if set(counts) != set(FIELDS) or any(type(v) is not int or v < 0 for v in counts.values()):
                        raise ValueError()
        for key in data['files']:
            if not re.fullmatch(r'[a-f0-9]{16}', key):
                raise ValueError()
            value = data['files'][key]
            if (type(value['offset']) is not int or value['offset'] < 0
                    or not re.fullmatch(r'[a-f0-9]{64}', value['anchor'])):
                raise ValueError()
        for day, minute in data['activity'].items():
            date.fromisoformat(day)
            if type(minute) is not int or not 0 <= minute < 1440:
                raise ValueError()
        for key, record in data['seen'].items():
            if not re.fullmatch(r'[a-f0-9]{64}', key):
                raise ValueError()
            date.fromisoformat(record['day'])
            if (model_name(record['model']) != record['model'] and record['model'] != '<unknown>'):
                raise ValueError()
            int(record['tier'])
            if (type(record['stamp']) not in (int, float) or not math.isfinite(record['stamp'])
                    or set(record['counts']) != set(FIELDS)
                    or any(type(v) is not int or v < 0 for v in record['counts'].values())):
                raise ValueError()
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
        return empty(signature)


def anchor(stream, offset):
    stream.seek(max(0, offset - 256))
    return sha(stream.read(min(offset, 256)))


def add_record(data, record, sign):
    bucket = data['days'].setdefault(record['day'], {}).setdefault(record['model'], {}).setdefault(
        record['tier'], dict.fromkeys(FIELDS, 0))
    for key in FIELDS:
        bucket[key] += sign * record['counts'][key]


class UsageScanner:
    def __init__(self, cache: Path, projects: Path | None = None, pricing: Pricing | None = None):
        self.cache = Path(cache)
        config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
        self.projects = Path(projects) if projects is not None else config / 'projects'
        self.pricing = pricing or Pricing()
        self.skipped = 0

    def scan(self, today: date | None = None, cancelled=lambda: False):
        today = today or datetime.now().astimezone().date()
        self.skipped = 0
        data = load_cache(self.cache, self.pricing.signature())
        # Boundary digests detect replacement, including same-size edits.
        paths = sorted(self.projects.rglob('*.jsonl')) if self.projects.exists() else []
        paths = [p for p in paths if p.is_file() and not p.is_symlink()]
        keyed = [(sha(str(p.absolute()).encode())[:16], p) for p in paths]
        rebuild = False
        readable = []
        for key, path in keyed:
            old = data['files'].get(key)
            try:
                with path.open('rb') as stream:
                    if old:
                        stat = path.stat()
                        if (stat.st_size < old['offset'] or anchor(stream, old['offset']) != old['anchor']
                                or old.get('identity') != stat.st_ino
                                or (stat.st_size == old.get('size') and stat.st_mtime_ns != old.get('modified'))):
                            rebuild = True
            except OSError:
                # A locked or unreadable transcript keeps its previous totals; try again next scan.
                self.skipped += 1
                continue
            readable.append((key, path))
        keyed_all, keyed = keyed, readable
        if rebuild:
            data = empty(self.pricing.signature())
        try:
            result, late = self._read(data, keyed, today, cancelled, full=not bool(data['files']))
            if late:
                self.skipped = len(keyed_all) - len(keyed)
                result, _ = self._read(empty(self.pricing.signature()), keyed, today, cancelled, full=True)
        except OSError:
            return None  # Read error part-way through a file: keep the old cache rather than risk double counting.
        if result is None or cancelled():
            return None
        cutoff = str(today - timedelta(days=55))
        result['days'] = {d: v for d, v in result['days'].items() if cutoff <= d <= str(today)}
        result['activity'] = {d: v for d, v in result['activity'].items() if cutoff <= d <= str(today)}
        recent = str(today - timedelta(days=7))
        result['seen'] = {k: v for k, v in result['seen'].items() if v['day'] >= recent}
        live = {key for key, _ in keyed_all}
        result['files'] = {k: v for k, v in result['files'].items() if k in live}  # Drop deleted transcripts.
        atomic_json(self.cache, result)
        return result

    def _read(self, initial, paths, today, cancelled, full=False):
        data = deepcopy(initial)
        oldest, recent = str(today - timedelta(days=55)), str(today - timedelta(days=7))
        for key, path in paths:
            if cancelled():
                return None, False
            offset = data['files'].get(key, {}).get('offset', 0)
            try:
                stream = path.open('rb')
            except OSError:
                self.skipped += 1  # Opened fine a moment ago; keep its old totals and offset.
                continue
            try:
                stream.seek(offset)
            except OSError:
                stream.close()
                self.skipped += 1
                continue
            with stream:
                while True:
                    if cancelled():
                        return None, False
                    start = stream.tell()
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if not line.endswith(b'\n'):
                        if len(line) <= MAX_LINE:
                            stream.seek(start)
                            break
                        while line and not line.endswith(b'\n'):
                            line = stream.readline(MAX_LINE + 1)
                        if not line:
                            stream.seek(start)
                            break
                        self.skipped += 1
                        continue
                    if len(line) > MAX_LINE:
                        self.skipped += 1
                        continue
                    # Timestamps are also needed on user records, even without usage.
                    if b'"timestamp"' not in line:
                        continue
                    try:
                        row = json.loads(line, object_pairs_hook=metadata)
                    except (ValueError, UnicodeError, RecursionError):
                        self.skipped += 1
                        continue
                    if not isinstance(row, dict) or row.get('type') not in ('user', 'assistant'):
                        continue
                    dt = timestamp(row.get('timestamp'))
                    if dt is None or not oldest <= str(dt.date()) <= str(today):
                        continue
                    activity_day = str((dt - timedelta(hours=5)).date())
                    minute = (dt.hour * 60 + dt.minute - 300) % 1440
                    data['activity'][activity_day] = max(minute, data['activity'].get(activity_day, -1))
                    msg = row.get('message')
                    if row.get('type') != 'assistant' or not isinstance(msg, dict) or not isinstance(msg.get('usage'), dict):
                        continue
                    ids = (msg.get('id'), row.get('requestId'))
                    if not any(ids) or any(v is not None and (not isinstance(v, str) or not v) for v in ids):
                        continue
                    counts = counts_from(msg['usage'])
                    if counts is None:
                        self.skipped += 1
                        continue
                    ident = sha(json.dumps(ids).encode())
                    model = model_name(msg.get('model'))
                    record = {'day': str(dt.date()), 'model': model, 'counts': counts,
                              'tier': self.pricing.tier(model, counts['in'] + counts['cw5'] + counts['cw1'] + counts['cr']),
                              'stamp': dt.timestamp()}
                    previous = data['seen'].get(ident)
                    if previous:
                        if record['stamp'] < previous['stamp'] or (record['stamp'] == previous['stamp'] and
                                (counts['out'] < previous['counts']['out'] or record == previous)):
                            continue
                        add_record(data, previous, -1)
                    elif record['day'] < recent and not full:
                        return None, True  # Expired dedup key: rebuild rather than double count.
                    add_record(data, record, 1)
                    data['seen'][ident] = record
                offset = stream.tell()
                stat = path.stat()
                data['files'][key] = {'offset': offset, 'anchor': anchor(stream, offset),
                                     'identity': stat.st_ino, 'size': stat.st_size, 'modified': stat.st_mtime_ns}
        return data, False
