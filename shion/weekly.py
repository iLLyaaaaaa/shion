"""Weekly counters, report data and configurable titles (no GUI)."""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from shion.limits import number

from shion.usage import FIELDS, Pricing

ROOT = Path(__file__).resolve().parents[1]
COUNTERS = ('tasks', 'seconds', 'approvals', 'denials', 'pats', 'snacks')


def clean_stats(raw):
    result = {}
    if not isinstance(raw, dict):
        return result
    for day, values in raw.items():
        try:
            date.fromisoformat(day)
        except (TypeError, ValueError):
            continue
        if isinstance(values, dict):
            result[day] = {k: v for k in COUNTERS if type(v := values.get(k)) is int and v >= 0}
            if number(values.get('seven_day_peak')):
                result[day]['seven_day_peak'] = values['seven_day_peak']
    return dict(sorted(result.items())[-56:])


def count(stats, now, key, value=1):
    day = str(now.date())
    stats.setdefault(day, {})[key] = stats.get(day, {}).get(key, 0) + value
    cutoff = str(now.date() - timedelta(days=55))
    for old in list(stats):
        if old < cutoff:
            del stats[old]


class WorkTimer:
    def __init__(self):
        self.starts = {}

    def event(self, kind, session, now, stats):
        if kind == 'prompt' and session:
            self.starts[session] = now
        elif kind == 'stop':
            count(stats, now, 'tasks')
            start = self.starts.pop(session, None)
            if start is not None:
                count(stats, now, 'seconds', min(7200, max(0, int((now - start).total_seconds()))))
        elif kind in ('work_stopped', 'pause_timeout', 'session_end'):
            self.starts.pop(session, None)


def week_start(today):
    return today - timedelta(days=today.weekday())


def title_for(metrics, lang, rules=None):
    rules = rules if rules is not None else json.loads((ROOT / 'assets/weekly_titles.json').read_text(encoding='utf-8'))
    for item in sorted(rules, key=lambda r: r['priority']):
        conditions = item.get('all', [])
        def matches(c):
            value = metrics.get(c['field'], 0)
            return value >= c.get('min', 0) and value <= c.get('max', float('inf'))
        if all(matches(c) for c in conditions) and (not item.get('any') or any(matches(c) for c in item['any'])):
            return {'name': item['name'].get(lang, item['name']['en']),
                    'comment': item['comment'].get(lang, item['comment']['en']), 'sprite': item['sprite']}
    raise ValueError('No fallback weekly title')


def report(start, stats, usage, lang='zh', enabled=True, pricing=None):
    days = [str(start + timedelta(days=i)) for i in range(7)]
    totals = {k: sum(stats.get(day, {}).get(k, 0) for day in days) for k in COUNTERS}
    selected = {d: usage.get('days', {}).get(d, {}) for d in days} if enabled else {}
    daily = []
    output = 0
    for day in days:
        token_counts = [c for tiers in selected.get(day, {}).values() for c in tiers.values()]
        daily.append(sum(sum(c.get(k, 0) for k in FIELDS) for c in token_counts))
        output += sum(c.get('out', 0) for c in token_counts)
    activity = {d: usage.get('activity', {}).get(d) for d in days}
    minutes = [m for m in activity.values() if type(m) is int and 0 <= m < 1440]
    latest = max(minutes) if minutes else None
    totals.update(total_tokens=sum(daily), output_tokens=output,
                  nights=sum(m >= 1200 for m in minutes),
                  approvals_denials_pats=totals['approvals'] + totals['denials'] + totals['pats'])
    price, partial = (pricing or Pricing()).estimate(selected)
    peaks = [stats.get(day, {}).get('seven_day_peak') for day in days]
    peaks = [v for v in peaks if number(v)]
    if peaks:
        totals['seven_day_peak'] = max(peaks)
        totals['quota'] = max(peaks)
    return {'start': str(start), 'end': str(start + timedelta(days=6)), 'totals': totals,
            'daily': daily if enabled else [stats.get(d, {}).get('tasks', 0) for d in days],
            'latest': f'{(latest + 300) // 60 % 24:02}:{(latest + 300) % 60:02}' if latest is not None else None,
            'title': title_for(totals, lang), 'price': price, 'partial': partial,
            'enabled': enabled, 'lang': lang}


def preview(lang='zh', enabled=True):
    start = date(2026, 10, 19)
    stats = {str(start + timedelta(days=i)): dict(tasks=i + 1, seconds=3500 + i * 500,
              approvals=4, denials=1, pats=3, snacks=2) for i in range(7)}
    usage = {'days': {str(start + timedelta(days=i)): {'claude-sonnet-5-5': {'0':
             dict(zip(FIELDS, (25000, 90000 + i * 20000, 40000, 5000, 2000000 + i * 100000)))}}
             for i in range(7)}, 'activity': {str(start): 1301, str(start + timedelta(days=1)): 1250}}
    return report(start, stats, usage, lang, enabled)
