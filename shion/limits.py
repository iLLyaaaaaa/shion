"""Metadata-only quota validation and session-scoped cosmetic stamina."""
import math

WINDOWS = ('five_hour', 'seven_day')


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def parse_limits(data):
    if not isinstance(data, dict) or set(data) - {'session', *WINDOWS}:
        raise ValueError('Invalid quota fields')
    sid = data.get('session')
    if not isinstance(sid, str) or not 0 < len(sid) <= 128 or any(ord(c) < 32 for c in sid):
        raise ValueError('Invalid session')
    result = {'session': sid}
    for key in WINDOWS:
        if key not in data:
            continue
        value = data[key]
        if (not isinstance(value, dict) or set(value) != {'used_percentage', 'resets_at'}
                or not number(value['used_percentage']) or not number(value['resets_at'])
                or value['resets_at'] <= 0 or value['resets_at'] > 253402300799):
            raise ValueError('Invalid quota window')
        result[key] = dict(value)
    return result


def clean_announced(raw):
    result = {}
    if not isinstance(raw, dict):
        return result
    for key, levels in raw.items():
        try:
            reset = float(key)
        except (ValueError, TypeError, OverflowError):
            continue
        if not number(reset) or not 0 < reset <= 253402300799 or not isinstance(levels, list):
            continue
        clean = sorted({level for level in levels if type(level) is int and 0 <= level <= 4})
        if clean:
            result[str(reset)] = clean
    return dict(sorted(result.items(), key=lambda item: float(item[0]))[-128:])


def clean_last(raw):
    """Last received seven_day value: {value, resets_at, at}; no session or content."""
    if not isinstance(raw, dict) or set(raw) != {'value', 'resets_at', 'at'}:
        return {}
    if not all(number(raw[k]) for k in raw):
        return {}
    if not 0 < raw['resets_at'] <= 253402300799 or not 0 < raw['at'] <= 253402300799:
        return {}
    return {k: raw[k] for k in ('value', 'resets_at', 'at')}


class Limits:
    def __init__(self, announced=None):
        self.sessions = {}
        self.down = set()
        self.level = 0
        self.pending = None
        self.reviving = False
        self.announced = {(level, ('terminal', (float(reset),)))
                          for reset, levels in clean_announced(announced).items() for level in levels}
        self._windows = set()

    def update(self, data, now):
        data = parse_limits(data)
        sid = data['session']
        if sid not in self.sessions and len(self.sessions) >= 128:
            self.sessions = {s: v for s, v in self.sessions.items()
                             if any(w['resets_at'] > now for w in v.values())}
            if len(self.sessions) >= 128:
                return
        self.sessions[sid] = {k: data[k] for k in WINDOWS if k in data}
        self.down.discard(sid)  # statusLine identifies this session's terminal path.
        self.refresh(now)

    def signal(self, sid, down, now):
        if not sid or sid in self.sessions or (down and sid not in self.down and len(self.down) >= 128):
            return
        revived = not down and sid in self.down
        if down:
            self.down.add(sid)
        else:
            self.down.discard(sid)
        self.refresh(now, revived=revived)

    def values(self, now):
        return {key: max((v[key]['used_percentage'] for v in self.sessions.values()
                          if key in v and v[key]['resets_at'] > now), default=None) for key in WINDOWS}

    def refresh(self, now, revived=False):
        fresh = [v['five_hour'] for v in self.sessions.values()
                 if 'five_hour' in v and v['five_hour']['resets_at'] > now]
        windows = {v['resets_at'] for v in fresh}
        value = max((v['used_percentage'] for v in fresh), default=0)
        level = 3 if self.down or value >= 95 else 2 if value >= 80 else 1 if value >= 50 else 0
        expired = any(reset <= now for reset in self._windows)
        chosen = max(fresh, key=lambda v: v['used_percentage'], default=None)
        key = ('hook', tuple(sorted(self.down))) if self.down else (
            'terminal', (chosen['resets_at'],) if chosen else ())
        notice = (level, key)
        if level and (level != self.level or windows != self._windows) and notice not in self.announced:
            self.pending = notice
        elif not level and self.level > 0 and (fresh or expired or revived):
            self.pending = None if (4, key) in self.announced else (0, key)
            self.reviving = self.pending is not None
        elif not level and fresh and windows != self._windows and notice not in self.announced:
            self.pending = notice
            self.reviving = False
        elif self.pending is not None and self.pending[0] != level:
            self.pending = None
        self.level, self._windows = level, windows
        # Expired terminal windows no longer need speech-dedup entries.
        self.announced = {item for item in self.announced
                          if (item[1][0] == 'hook' and self.down)
                          or (item[1][0] == 'terminal' and any(reset > now for reset in item[1][1]))}

    def acknowledge(self):
        if self.pending is not None:
            level, key = self.pending
            self.announced.add((4 if level == 0 and self.reviving else level, key))
            self.pending = None

    def clear(self):
        self.__init__(self.records(0))

    def records(self, now):
        result = {}
        for level, (source, resets) in self.announced:
            if source == 'terminal':
                for reset in resets:
                    if reset > now:
                        result.setdefault(str(float(reset)), []).append(level)
        return clean_announced(result)
