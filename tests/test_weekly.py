import copy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication

from shion import state as S
from shion.usage import Pricing, UsageScanner, FIELDS, counts_from
from shion.weekly import WorkTimer, clean_stats, preview, report, title_for, week_start
from shion.weekly_ui import FONTS, WeeklyWindow, number, render_card
from tests.test_controller import env  # noqa: F401

TODAY = date(2026, 11, 2)


def row(mid='a', inp=10, out=20, cw=30, cr=40, stamp='2026-11-02T06:00:00Z', model='claude-haiku-5-5', split=None):
    usage = dict(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cw, cache_read_input_tokens=cr)
    if split is not None:
        usage['cache_creation'] = split
    return {'type': 'assistant', 'timestamp': stamp, 'requestId': 'request-' + mid,
            'cwd': 'PRIVATE_DIRECTORY', 'message': {'id': mid, 'model': model,
            'content': 'PRIVATE_CONVERSATION', 'usage': usage}}


def write(path, rows, mode='w'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding='utf-8') as stream:
        for item in rows:
            stream.write(json.dumps(item) + '\n')


def scanner(tmp_path):
    return UsageScanner(tmp_path / 'cache.json', tmp_path / 'projects')


def test_prices_require_explicit_version_and_unknown_opus_41():
    pricing = Pricing()
    assert pricing.model('claude-opus-4-1') is None
    assert pricing.model('claude-opus-4') is None
    assert pricing.model('claude-opus-5-9') is None
    assert pricing.model('claude-sonnet-5-5-20261001') is not None
    assert pricing.model('claude-sonnet-5-5-private') is None
    assert Pricing({'models': 'invalid'}).model('claude-opus-5-5') is None


@pytest.mark.parametrize('tokens,tier', [(0, '0'), (100000, '0'), (100001, '100000')])
def test_tier_boundary(tokens, tier):
    assert Pricing().tier('claude-haiku-5-5', tokens) == tier


def test_each_message_tier_includes_both_cache_kinds(tmp_path):
    scan = scanner(tmp_path)
    p = scan.projects / 'rows.jsonl'
    write(p, [row('a', inp=1, cr=99998, cw=1), row('b', inp=1, cr=100000, cw=1,
          split={'ephemeral_1h_input_tokens': 1})])
    result = scan.scan(TODAY)
    tiers = next(iter(result['days'].values()))['claude-haiku-5-5']
    assert tiers['0']['cr'] == 99998
    assert tiers['100000']['cw1'] == 1 and tiers['100000']['cw5'] == 0
    price, partial = Pricing().estimate(result['days'])
    expected = (1 * .1 + 20 * .5 + .125 + 99998 * .01 + .5 + 20 * 2.5 + 1 + 100000 * .05) / 1e6
    assert price == pytest.approx(expected) and not partial


def test_cache_ttl_fallback_and_inconsistent_counts():
    assert counts_from({'cache_creation_input_tokens': 100})['cw5'] == 100
    assert counts_from({'cache_creation_input_tokens': 100, 'cache_creation': {'ephemeral_1h_input_tokens': 40}})['cw5'] == 60
    assert counts_from({'cache_creation_input_tokens': 5, 'cache_creation': {'ephemeral_1h_input_tokens': 6}}) is None
    assert counts_from({'input_tokens': True}) is None


def test_dedup_incremental_update_restart_and_truncation(tmp_path):
    scan = scanner(tmp_path)
    p = scan.projects / 'rows.jsonl'
    write(p, [row(), row()])
    a = scan.scan(TODAY)
    assert len(a['seen']) == 1
    write(p, [row(out=80, stamp='2026-11-02T06:01:00Z')], 'a')
    b = scanner(tmp_path).scan(TODAY)
    counts = next(iter(b['days'].values()))['claude-haiku-5-5']['0']
    assert counts['out'] == 80
    assert scanner(tmp_path).scan(TODAY)['days'] == b['days']
    write(p, [row('replacement', out=7)])
    c = scanner(tmp_path).scan(TODAY)
    assert next(iter(c['days'].values()))['claude-haiku-5-5']['0']['out'] == 7


def test_incomplete_tail_does_not_advance_offset(tmp_path):
    scan = scanner(tmp_path); p = scan.projects / 'rows.jsonl'
    write(p, [row()])
    complete = p.read_bytes()
    pending = json.dumps(row('b')).encode()
    p.write_bytes(complete + pending[:50])
    first = scan.scan(TODAY)
    assert next(iter(first['files'].values()))['offset'] == len(complete)
    p.write_bytes(complete + pending + b'\n')
    assert len(scan.scan(TODAY)['seen']) == 2


def test_same_timestamp_stream_update_moves_tier_and_cache_detail(tmp_path):
    scan = scanner(tmp_path); p = scan.projects / 'rows.jsonl'
    write(p, [row(cw=99950, inp=10, cr=10)])
    scan.scan(TODAY)
    write(p, [row(cw=100000, inp=10, cr=10, split={'ephemeral_1h_input_tokens': 100000})], 'a')
    data = scan.scan(TODAY)
    tiers = next(iter(data['days'].values()))['claude-haiku-5-5']
    assert sum(tiers['0'].values()) == 0
    assert tiers['100000']['cw1'] == 100000


def test_malformed_cache_metadata_rebuilds_instead_of_stalling(tmp_path):
    scan = scanner(tmp_path); write(scan.projects / 'rows.jsonl', [row()])
    good = scan.scan(TODAY)
    broken = copy.deepcopy(good)
    next(iter(broken['files'].values()))['offset'] = 'invalid'
    scan.cache.write_text(json.dumps(broken), encoding='utf-8')
    assert scan.scan(TODAY)['days'] == good['days']


def test_late_expired_key_rebuild_and_retention(tmp_path):
    scan = scanner(tmp_path); p = scan.projects / 'rows.jsonl'
    old = row('old', stamp='2026-10-20T06:00:00Z')
    write(p, [old, row('ancient', stamp='2026-01-01T00:00:00Z')])
    a = scan.scan(TODAY)
    assert not a['seen'] and len(a['days']) == 1
    write(p, [old], 'a')
    assert scan.scan(TODAY)['days'] == a['days']


def test_scan_is_read_only_and_disk_cache_is_private(tmp_path):
    scan = scanner(tmp_path); p = scan.projects / 'PRIVATE_FILE.jsonl'
    write(p, [row()]); before = p.read_bytes()
    scan.scan(TODAY)
    assert p.read_bytes() == before
    cache = scan.cache.read_text()
    assert all(word not in cache for word in ('PRIVATE', 'request-a', str(p), 'content', 'cwd'))
    assert len(json.loads(cache)['seen'].popitem()[0]) == 64


def test_price_edit_does_not_require_rescan_or_change_cache(tmp_path):
    scan = scanner(tmp_path); write(scan.projects / 'x.jsonl', [row()])
    data = scan.scan(TODAY)
    changed = copy.deepcopy(Pricing().data)
    for model in changed['models']:
        for tier in model['tiers']:
            tier['rates'] = {k: v * 2 for k, v in tier['rates'].items()}
    pricing = Pricing(changed)
    assert pricing.signature() == scan.pricing.signature()
    assert pricing.estimate(data['days'])[0] == pytest.approx(Pricing().estimate(data['days'])[0] * 2)


def test_corrupt_cache_missing_directory_cancel_and_bad_rows(tmp_path):
    scan = scanner(tmp_path)
    scan.cache.write_text('broken')
    assert scan.scan(TODAY)['days'] == {}
    write(scan.projects / 'bad.jsonl', [{'type': 'assistant', 'timestamp': 'bad'}, row(inp=-1)])
    with (scan.projects / 'bad.jsonl').open('ab') as stream:
        stream.write(b'{"timestamp":broken}\n' + b'x' * (1024 * 1024 + 1) + b'\n')
    assert scan.scan(TODAY)['days'] == {}
    before = scan.cache.read_bytes()
    assert scan.scan(TODAY, cancelled=lambda: True) is None
    assert scan.cache.read_bytes() == before


def test_activity_uses_transcript_timestamps_and_five_am_boundary(tmp_path):
    scan = scanner(tmp_path)
    # Explicit local offset avoids depending on the host's timezone in the assertion.
    tz = datetime.now().astimezone().tzinfo
    late = datetime(2026, 11, 2, 2, 41, tzinfo=tz)
    write(scan.projects / 'x.jsonl', [{'type': 'user', 'timestamp': late.isoformat(), 'message': 'PRIVATE'}])
    data = scan.scan(TODAY)
    assert data['activity'] == {'2026-11-01': 1301}
    card = report(date(2026, 10, 26), {}, data)
    assert card['latest'] == '02:41' and card['totals']['nights'] == 1


def test_weekly_counter_migration_and_timer():
    old = S.SaveData.from_dict({'schema_version': 5, 'weekly_stats': {'bad': 1}, 'usage_enabled': 'bad'})
    assert old.weekly_stats == {} and old.usage_enabled
    timer = WorkTimer(); stats = {}; now = datetime(2026, 11, 2, 12)
    timer.event('prompt', 'a', now, stats)
    timer.event('prompt', 'b', now, stats)
    timer.event('stop', 'a', now + timedelta(hours=4), stats)
    timer.event('work_stopped', 'b', now, stats)
    assert stats['2026-11-02']['seconds'] == 7200
    assert stats['2026-11-02']['tasks'] == 1
    assert not timer.starts
    assert S.SaveData.from_dict(S.SaveData(weekly_stats=stats).to_dict()).weekly_stats == stats
    assert S.SaveData().schema_version == 5


def test_weekly_retention_also_applies_on_idle_startup():
    data = S.SaveData(weekly_stats={'2026-01-01': {'tasks': 1}, '2026-11-02': {'tasks': 2}})
    S.PetState(data, datetime(2026, 11, 2, 12))
    assert data.weekly_stats == {'2026-11-02': {'tasks': 2}}


def test_report_weeks_no_quota_unknown_models_and_title_boundary():
    assert week_start(date(2026, 11, 1)) == date(2026, 10, 26)
    assert title_for({'total_tokens': 199999999, 'tasks': 3}, 'zh')['name'] == '勤劳搭档'
    assert title_for({'total_tokens': 200000000, 'tasks': 3}, 'zh')['name'] == '吞金兽'
    data = {'days': {'2026-11-02': {'claude-opus-4-1': {'0': dict.fromkeys(FIELDS, 10)}}}}
    card = report(TODAY, {}, data)
    assert card['partial'] and 'quota' not in card and card['price'] == 0
    assert report(TODAY, {}, data, enabled=False)['totals']['total_tokens'] == 0


def test_controller_tracks_independent_sessions_and_interrupted_stop(env):
    ctl = env.ctl
    ctl.handle_event('prompt', meta={'session': 'a'})
    ctl.handle_event('prompt', meta={'session': 'b'})
    env.now += timedelta(minutes=10)
    ctl.handle_event('stop', meta={'session': 'a'})
    ctl.handle_event('work_stopped', meta={'session': 'b'})
    ctl.handle_event('stop', meta={'session': 'b'})
    stats = env.data.weekly_stats[str(env.now.date())]
    assert stats['tasks'] == 1 and stats['seconds'] == 600
    assert not ctl._work_timer.starts
    env.win.patted.emit()
    assert stats['pats'] == 1


def test_weekly_menu_opens_correct_week_and_switches_hide_numbers(env):
    from tests.test_controller import find_action
    ctl = env.ctl
    ctl.usage.data = {'days': {}, 'activity': {}}
    menu = ctl.build_menu()
    find_action(menu, '上一周').trigger()
    assert ctl._weekly_window.data['start'] == str(week_start(env.now.date()) - timedelta(days=7))
    assert ctl.usage.due is not None
    find_action(menu, '统计用量').trigger()
    assert not env.data.usage_enabled and not ctl._weekly_window.data['enabled']
    assert ctl.usage.due is None and ctl.usage.cancel.is_set()
    find_action(menu, '周报显示项目链接').trigger()
    assert not ctl._weekly_window.branding


def test_weekly_notice_waits_for_greeting_and_permission_then_once(env):
    ctl = env.ctl
    ctl.greet_startup(False)
    ctl._try_weekly_notice(env.now)
    assert not ctl._weekly_offer
    env.mono[0] += 100
    pending = ctl.hub.permissions.open('Bash', 'synthetic')
    ctl._try_weekly_notice(env.now)
    assert not ctl._weekly_offer
    ctl.hub.permissions.withdraw(pending)
    ctl._try_weekly_notice(env.now)
    assert ctl._weekly_offer
    ctl._on_click()
    assert ctl._weekly_previous and ctl._weekly_window.isVisible()
    assert env.data.weekly_announced == str(week_start(env.now.date()))


def test_permission_counts_only_actual_decisions(env):
    ctl = env.ctl
    pending = ctl.hub.permissions.open('Bash', 'synthetic')
    ctl._on_permission_decided(pending, False)
    ctl._on_permission_decided(pending, False)
    assert env.data.weekly_stats[str(env.now.date())]['denials'] == 1


def test_background_scanner_is_disabled_and_rate_limited(tmp_path, monkeypatch):
    from shion.usage_service import UsageService
    import time
    service = UsageService(tmp_path)
    called = []
    monkeypatch.setattr(service.scanner, 'scan', lambda *a: called.append(1) or {'days': {}, 'activity': {}})
    try:
        service.request(30)
        service.poll(True)
        assert service.future is None
        service.poll(False)
        assert service.due is None and not called
        service.request()
        service.poll(True)
        deadline = time.monotonic() + 2
        while service.future is not None and time.monotonic() < deadline:
            service.poll(True)
        assert called == [1] and not service.failed
    finally:
        service.close()


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
def test_card_and_window_are_exportable_without_focus(qapp, lang, tmp_path):
    card = preview(lang)
    image = render_card(card)
    assert (image.width(), image.height()) == (1200, 1500)
    assert image.save(str(tmp_path / 'weekly.png'))
    assert FONTS == ['Microsoft YaHei', 'Yu Gothic', 'Consolas']
    window = WeeklyWindow(card)
    assert window.testAttribute(__import__('PySide6.QtCore', fromlist=['Qt']).Qt.WA_ShowWithoutActivating)
    window.update_report(preview(lang, enabled=False))
    assert not window.data['enabled']
    window.close(); window.deleteLater()
    assert number(200000000, lang) in ('2亿', '200M', '2億')


def test_card_uses_shion_palette_and_highlights_only_peak(qapp):
    image = render_card(preview())
    assert image.pixelColor(0, 0).name().upper() == '#1A1212'
    assert image.pixelColor(100, 1200).name().upper() == '#5A3A2C'
    assert image.pixelColor(1040, 1200).name().upper() == '#F4772E'


def test_window_escape_save_and_clipboard_under_mocked_ui(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from shion import weekly_ui
    output = tmp_path / 'export.png'
    copied = []
    monkeypatch.setattr(weekly_ui.QFileDialog, 'getSaveFileName', lambda *args: (str(output), 'PNG'))
    monkeypatch.setattr(weekly_ui.QApplication, 'clipboard', lambda: type('Clipboard', (), {'setImage': lambda _, image: copied.append(image.copy())})())
    window = WeeklyWindow(preview())
    window.show()
    window.save_button.click()
    window.copy_button.click()
    assert output.is_file() and copied[0] == window.image
    QTest.keyClick(window, Qt.Key_Escape)
    assert not window.isVisible()
    window.deleteLater()


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
@pytest.mark.parametrize('peak_day', [0, 6])
def test_first_and_last_peak_labels_are_centered_and_within_margins(qapp, monkeypatch, lang, peak_day):
    from PySide6.QtGui import QPainter
    from PySide6.QtCore import QRectF
    from shion.lines import Lines
    draws = []
    original = QPainter.drawText

    def capture(painter, *args):
        if isinstance(args[0], QRectF) and args[-1] == Lines(lang).ui('weekly_peak'):
            draws.append((QRectF(args[0]), painter.fontMetrics().horizontalAdvance(args[-1]),
                          painter.font().pixelSize()))
        return original(painter, *args)

    monkeypatch.setattr(QPainter, 'drawText', capture)
    data = preview(lang)
    data['daily'] = [80] * 7
    data['daily'][peak_day] = 100
    image = render_card(data)
    assert len(draws) == 1  # The label stays complete, with no clipped ellipsis.
    bounds, text_width, font_size = draws[0]
    assert bounds.center().x() == pytest.approx(85 + 153 * peak_day + 95 / 2)
    assert bounds.left() >= 64 and bounds.right() <= 1136
    assert text_width <= bounds.width() and font_size <= 20
    colors = [image.pixelColor(100 + 153 * day, 1200).name().upper() for day in range(7)]
    assert colors.count('#F4772E') == 1 and colors[peak_day] == '#F4772E'
    assert image.pixelColor(100, 1006).name().upper() == '#33241F'


def test_token_numbers_share_baseline_and_english_header_is_weekly(qapp, monkeypatch):
    from PySide6.QtGui import QPainter
    from PySide6.QtCore import QPointF
    original = QPainter.drawText
    draws = []

    def capture(painter, *args):
        draws.append(args)
        return original(painter, *args)

    monkeypatch.setattr(QPainter, 'drawText', capture)
    data = preview('en')
    render_card(data)
    values = {number(data['totals'][key], 'en') for key in ('total_tokens', 'output_tokens')}
    baselines = [args[0].y() for args in draws if isinstance(args[0], QPointF) and args[-1] in values]
    assert len(baselines) == 2 and baselines[0] == baselines[1]
    assert any(args[-1] == '> SHION / WEEKLY' for args in draws)


def test_japanese_font_has_no_added_spacing_and_uses_proportional_kana(qapp):
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
    from shion.weekly_ui import card_font
    render_card(preview('ja'))  # Initialize installed fonts for the offscreen platform.
    font = card_font('ja', 58, True)
    assert font.families() == ['Yu Gothic UI', 'Yu Gothic', 'Microsoft YaHei', 'Consolas']
    assert card_font('ja', 28).weight() == QFont.Medium
    assert font.letterSpacingType() == QFont.AbsoluteSpacing and font.letterSpacing() == 0
    assert font.wordSpacing() == 0
    if 'Yu Gothic UI' in QFontDatabase.families():
        # UI already has proportional kana; palt is intentionally idempotent.
        metrics = QFontMetricsF(font)
        assert metrics.horizontalAdvance('夜更かしさん') < metrics.horizontalAdvance('夜' * 6)
