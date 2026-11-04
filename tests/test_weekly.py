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
    find_action(menu, '诗音周报').trigger()
    window = ctl._weekly_window
    assert window.data['start'] == str(week_start(env.now.date()) - timedelta(days=7))
    assert window.prev_button.isChecked() and window.data['title'] is not None
    assert ctl.usage.due is not None
    window.this_button.click()
    assert window.data['start'] == str(week_start(env.now.date())) and window.data['ongoing']
    assert window.this_button.isChecked() and window.data['title'] is None
    window.prev_button.click()
    assert window.data['start'] == str(week_start(env.now.date()) - timedelta(days=7))
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
    assert ctl.state.current(env.now) == 'cheer'
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
    assert number(200000000, lang) in ('2.00亿', '200M', '2.00億')


def test_card_uses_shion_palette_and_highlights_only_peak(qapp):
    image = render_card(preview())
    assert image.pixelColor(0, 0).name().upper() == '#1A1212'
    assert image.pixelColor(100, 1340).name().upper() == '#5A3A2C'
    assert image.pixelColor(1040, 1340).name().upper() == '#F4772E'


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


def test_unpriced_ignores_synthetic_and_all_zero_entries():
    zero = dict.fromkeys(FIELDS, 0)
    days = {'2026-11-02': {'<synthetic>': {'0': dict.fromkeys(FIELDS, 5)},
                           'claude-opus-4-1': {'0': zero}, 'claude-haiku-5-5': {'0': dict.fromkeys(FIELDS, 10)}}}
    price, partial = Pricing().estimate(days)
    assert price > 0 and not partial
    days['2026-11-02']['claude-opus-4-1'] = {'0': dict.fromkeys(FIELDS, 1)}
    assert Pricing().estimate(days)[1]


def test_synthetic_model_is_kept_and_old_cache_version_rebuilds(tmp_path):
    from shion.usage import load_cache, model_name
    assert model_name('<synthetic>') == '<synthetic>' and model_name('gpt-x') == '<unknown>'
    write(tmp_path / 'projects/p/a.jsonl', [row('s', model='<synthetic>', inp=0, out=0, cw=0, cr=0)])
    result = scanner(tmp_path).scan(TODAY)
    assert '<synthetic>' in result['days']['2026-11-02']
    cache = tmp_path / 'cache.json'
    old = json.loads(cache.read_text(encoding='utf-8'))
    old['version'] = 1
    cache.write_text(json.dumps(old), encoding='utf-8')
    assert load_cache(cache, Pricing().signature())['days'] == {}


def usage_for(start, values):
    return {'days': {str(start + timedelta(days=i)): {'claude-haiku-5-5': {'0': dict(zip(FIELDS, (v, 0, 0, 0, 0)))}}
                     for i, v in enumerate(values) if v}, 'activity': {}}


def test_ongoing_week_has_no_title_future_days_and_peak_includes_today():
    start = date(2026, 11, 2)
    usage = usage_for(start, [100, 300, 900, 0, 0, 0, 0])  # today (Wednesday) is the largest
    card = report(start, {}, usage, today=date(2026, 11, 4))
    assert card['ongoing'] and card['day_n'] == 3 and card['title'] is None
    assert card['future'] == [False, False, False, True, True, True, True]
    assert card['peak_day'] == 2  # today counts; future days never do
    monday = report(start, {}, usage, today=start)
    assert monday['day_n'] == 1 and monday['peak_day'] == 0
    assert report(start, {}, usage_for(start, [0] * 7), today=start)['peak_day'] is None
    finished = report(start, {}, usage, today=date(2026, 11, 9))
    assert not finished['ongoing'] and finished['title'] and finished['peak_day'] == 2
    assert not any(finished['future'])
    assert report(start, {}, usage, today=date(2026, 11, 8))['ongoing']  # Sunday is still running


def test_easy_week_uses_token_days_not_shion_counters():
    start = date(2026, 10, 26)
    stats = {str(start): {'tasks': 0}}
    one_day = report(start, stats, usage_for(start, [5, 0, 0, 0, 0, 0, 0]), today=TODAY)
    assert one_day['totals']['usage_days'] == 1 and one_day['title']['name'] == '摸鱼周'
    busy = report(start, stats, usage_for(start, [5, 5, 0, 0, 0, 0, 0]), today=TODAY)
    assert busy['title']['name'] == '勤劳搭档'
    off = report(start, stats, usage_for(start, [5, 0, 0, 0, 0, 0, 0]), enabled=False, today=TODAY)
    assert 'usage_days' not in off['totals'] and off['title']['name'] == '勤劳搭档'


def test_shion_counters_empty_flag():
    start = date(2026, 10, 26)
    assert not report(start, {}, usage_for(start, [5] * 7), today=TODAY)['has_stats']
    assert report(start, {str(start): {'pats': 1}}, {}, today=TODAY)['has_stats']


@pytest.mark.parametrize('value, zh, en', [
    (42894321, '4289万', '43M'), (123456789, '1.23亿', '123M'), (1234567890, '12.35亿', '1.23B'),
    (5234567, '523.5万', '5.2M'), (99999999, '1.00亿', '100M'), (999999999, '10.00亿', '1.00B'), (950, '950', '950')])
def test_number_rounding(value, zh, en):
    assert number(value, 'zh') == zh and number(value, 'en') == en
    assert number(value, 'ja') == zh.replace('亿', '億')


def capture_texts(monkeypatch):
    from PySide6.QtGui import QPainter
    seen = []
    original = QPainter.drawText

    def capture(painter, *args):
        if args[-1]:
            seen.append((painter.font().pixelSize(), args[-1]))
        return original(painter, *args)
    monkeypatch.setattr(QPainter, 'drawText', capture)
    return seen


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
def test_card_text_is_at_least_28px(qapp, monkeypatch, lang):
    seen = capture_texts(monkeypatch)
    render_card(preview(lang))
    start = date(2026, 11, 2)
    render_card(report(start, {}, usage_for(start, [10 ** 7, 0, 0]), lang, today=date(2026, 11, 3)))
    assert seen and min(size for size, _ in seen) >= 28


def test_ongoing_card_shows_day_and_empty_stats_line_without_future_numbers(qapp, monkeypatch):
    from shion.lines import Lines
    seen = capture_texts(monkeypatch)
    start = date(2026, 11, 2)
    card = report(start, {}, usage_for(start, [10 ** 7, 0, 0]), today=date(2026, 11, 3))
    image = render_card(card)
    texts = [t for _, t in seen]
    ui = Lines('zh').ui
    assert ui('weekly_ongoing', n=2) in texts and ui('weekly_active_days') in texts and '1/2' in texts
    assert ui('weekly_tasks') not in texts and ui('weekly_peak') in texts
    assert texts.count('0') == 2  # output tokens and Tuesday (today); future days show no number.
    assert image.pixelColor(85 + 153 * 4 + 47, 1220).name().upper() == '#1A1212'  # dashed box is hollow


def test_window_repaints_at_real_size_and_fills_85_percent(qapp, monkeypatch):
    from shion import weekly_ui
    painted = []
    original = weekly_ui.paint_card
    monkeypatch.setattr(weekly_ui, 'paint_card', lambda p, *a: painted.append(p.device().width()) or original(p, *a))
    window = WeeklyWindow(preview())
    screen = window.screen() or QApplication.primaryScreen()
    assert abs(window.height() - screen.availableGeometry().height() * 0.85) <= 2
    assert abs(window.view.width() / window.view.height() - 1200 / 1500) < 0.01
    window.view.grab()
    assert window.view.width() in painted  # painted straight onto the widget, at its own size
    assert window.image.width() == 1200 and window.image.height() == 1500
    assert '#1A1212' in window.styleSheet() and '#F4772E' in window.styleSheet()
    window.close(); window.deleteLater()


EXPECTED_TITLES = {
    'quota': ('collapse', '额度都快被你榨干了……诗音也要倒下了啦'),
    'night': ('yawn', '半夜还在写代码……诗音都困了，快去睡觉！'),
    'gold': ('cheer', '这周的 token 一口一口全吃光啦，好能吃！'),
    'approval': ('done', '批准、批准、再批准——手速真快呢'),
    'hands_off': ('idle', '活全丢给 AI 干，自己去摸鱼了吧？哼，诗音都看见了'),
    'treats': ('happy', '零食和摸头都收到啦……诗音才、才没有很开心！'),
    'quiet': ('slump', '这周很悠闲嘛……偶尔休息一下也不错'),
    'partner': ('done', '这周也一起走过来了，辛苦啦！'),
}


def test_titles_have_new_comments_sprites_and_no_product_name():
    from shion.lines import Lines
    rules = json.loads((Path(__file__).parents[1] / 'assets/weekly_titles.json').read_text(encoding='utf-8'))
    assert {r['id'] for r in rules} == set(EXPECTED_TITLES)
    for rule in rules:
        sprite, zh = EXPECTED_TITLES[rule['id']]
        assert rule['sprite'] == sprite and rule['comment']['zh'] == zh
        assert (Path(__file__).parents[1] / 'assets/sprites' / (sprite + '.png')).is_file()
        for lang in ('zh', 'en', 'ja'):
            assert rule['name'][lang] and rule['comment'][lang]
    quota = next(r for r in rules if r['id'] == 'quota')
    assert quota['name']['ja'] == '枠キラー'
    assert next(r for r in rules if r['id'] == 'hands_off')['comment']['en'].startswith('Left all the work to the AI')
    blob = json.dumps(rules, ensure_ascii=False)
    for lang in ('zh', 'en', 'ja'):
        ui = Lines(lang).ui
        blob += ''.join(ui(k) for k in ('weekly_report', 'weekly_active_days', 'weekly_daily_avg', 'weekly_latest_label',
                                        'weekly_estimate', 'weekly_partial', 'weekly_ongoing', 'weekly_quota'))
    assert 'claude' not in blob.lower()


def test_active_days_and_daily_average_use_elapsed_days():
    start = date(2026, 11, 2)
    usage = usage_for(start, [100, 0, 300, 0, 0, 0, 0])
    ongoing = report(start, {}, usage, today=date(2026, 11, 4))
    assert ongoing['active_days'] == 2 and ongoing['days_elapsed'] == 3 and ongoing['daily_avg'] == pytest.approx(400 / 3)
    finished = report(start, {}, usage, today=date(2026, 11, 9))
    assert finished['active_days'] == 2 and finished['days_elapsed'] == 7 and finished['daily_avg'] == pytest.approx(400 / 7)
    off = report(start, {}, usage, enabled=False, today=date(2026, 11, 9))
    assert off['active_days'] is None and off['daily_avg'] is None


def test_stats_always_show_token_items_and_counters_only_when_recorded(qapp, monkeypatch):
    from shion.lines import Lines
    ui = Lines('zh').ui
    start = date(2026, 10, 26)
    seen = capture_texts(monkeypatch)
    render_card(report(start, {}, usage_for(start, [10 ** 6] * 6 + [0]), today=TODAY))
    texts = [t for _, t in seen]
    assert '6/7' in texts and ui('weekly_daily_avg') in texts and ui('weekly_latest_label') in texts
    assert ui('weekly_tasks') not in texts and ui('weekly_pats') not in texts
    seen.clear()
    render_card(report(start, {str(start): {'tasks': 3, 'pats': 2}}, usage_for(start, [10 ** 6] * 6 + [0]), today=TODAY))
    texts = [t for _, t in seen]
    assert ui('weekly_tasks') in texts and ui('weekly_snacks') in texts and ui('weekly_latest_label') in texts


def capture_boxes(monkeypatch):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    boxes = {}
    original = QPainter.drawText

    def capture(painter, *args):
        if isinstance(args[0], (QRectF, QPointF)):
            boxes[args[-1]] = args[0]
        return original(painter, *args)
    monkeypatch.setattr(QPainter, 'drawText', capture)
    return boxes


class Draws:
    """Records every drawText/drawImage/drawEllipse call of a card render."""

    def __init__(self):
        self.texts, self.images, self.ellipses = [], [], []

    def by_text(self, value):
        return [t for t in self.texts if t['text'] == value]

    def one(self, value):
        found = self.by_text(value)
        assert len(found) == 1, (value, len(found))
        return found[0]


@pytest.fixture
def draws(monkeypatch):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainter
    record = Draws()
    text_original, image_original, ellipse_original = QPainter.drawText, QPainter.drawImage, QPainter.drawEllipse

    def text(painter, *args):
        geometry = args[0]
        if isinstance(geometry, (QRectF, QPointF)):
            font = painter.font()
            record.texts.append(dict(text=args[-1], geom=geometry, size=font.pixelSize(), bold=font.bold(),
                                     family=(font.families() or [font.family()])[0],
                                     color=painter.pen().color().name().upper(),
                                     advance=painter.fontMetrics().horizontalAdvance(args[-1])))
        return text_original(painter, *args)

    def image(painter, *args):
        record.images.append(QRectF(args[0]))
        return image_original(painter, *args)

    def ellipse(painter, *args):
        record.ellipses.append(args)
        return ellipse_original(painter, *args)

    monkeypatch.setattr(QPainter, 'drawText', text)
    monkeypatch.setattr(QPainter, 'drawImage', image)
    monkeypatch.setattr(QPainter, 'drawEllipse', ellipse)
    return record


def finished_card(lang='zh', **changes):
    start = date(2026, 10, 26)
    stats = {str(start + timedelta(days=i)): dict(tasks=3, seconds=3600, approvals=4, denials=1, pats=2, snacks=1)
             for i in range(7)}
    usage = {'days': {str(start + timedelta(days=i)): {'claude-sonnet-5-5': {'0': dict(zip(FIELDS, (
        10, 20000 + i * 1000, 5, 5, 1000000 * (i + 1))))}} for i in range(7)}, 'activity': {str(start): 1301}}
    return {**report(start, stats, usage, lang, True, today=date(2026, 11, 3)), **changes}


def test_range_label_drops_repeated_year_but_keeps_it_across_years():
    from shion.weekly_ui import range_label
    assert range_label('2026-10-26', '2026-11-01') == '2026.10.26 — 11.01'
    assert range_label('2026-12-28', '2027-01-03') == '2026.12.28 — 2027.01.03'


def test_top_bar_date_is_centered_on_sprite_axis_and_on_header_row(qapp, draws):
    card = finished_card()
    render_card(card)
    date_text = draws.one('2026.10.26 — 11.01')
    header = draws.one('> SHION / 诗音周报')
    assert date_text['size'] == 30 and date_text['geom'].center().x() == pytest.approx((689 + 1066) / 2, abs=1)
    assert date_text['geom'].center().y() == header['geom'].center().y() and 64 <= header['geom'].y() <= 110


def test_sprite_and_glow_sit_beside_total_number_above_the_grid(qapp, draws):
    render_card(finished_card())
    sprite = draws.images[0]
    assert sprite.top() == 225 and sprite.bottom() == pytest.approx(655, abs=1) and sprite.height() == pytest.approx(430, abs=1)
    assert 689 <= sprite.left() and sprite.right() <= 1066.5 and sprite.bottom() < 753
    center, radius_x, radius_y = draws.ellipses[0]
    assert (center.x(), center.y()) == (sprite.center().x(), 440) and radius_x == radius_y
    total = draws.one(number(finished_card()['totals']['total_tokens'], 'zh'))
    assert total['size'] == 136 and total['bold'] and total['color'] == '#F4772E' and total['geom'].x() == 64
    assert total['geom'].y() <= 655 and total['geom'].x() + total['advance'] < sprite.left()


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
def test_title_area_has_label_big_bold_title_and_two_line_comment(qapp, draws, lang):
    from shion.lines import Lines
    card = finished_card(lang)
    render_card(card)
    assert draws.one(Lines(lang).ui('weekly_title_label'))['color'] == '#9C8A84'
    title = draws.one(card['title']['name'])
    assert title['bold'] and title['color'] == '#F4772E' and 60 <= title['size'] <= 128
    parts = [t for t in draws.texts if t['size'] == 34]
    assert 1 <= len(parts) <= 2 and ''.join(p['text'] for p in parts).replace(' ', '') == card['title']['comment'].replace(' ', '')


def test_grid_is_three_by_two_rounded_cards_with_accent_on_busiest_day(qapp, draws):
    from shion.lines import Lines
    ui = Lines('zh').ui
    card = finished_card()
    image = render_card(card)
    labels = [ui('weekly_output'), ui('weekly_price_label'), ui('weekly_daily_avg'),
              ui('weekly_active_days'), ui('weekly_latest_label'), ui('weekly_peak')]
    rects = [draws.one(label)['geom'] for label in labels]
    assert [r.x() - 22 for r in rects[:3]] == [64, 64 + 364, 64 + 728] == [r.x() - 22 for r in rects[3:]]
    assert rects[0].y() - 14 == 753 and rects[3].y() > rects[0].y() + 124
    fill, edge, accent = '#231917', '#33241F', '#F4772E'
    for i, rect in enumerate(rects):
        x, y = rect.x() - 22, rect.y() - 14
        assert image.pixelColor(int(x) + 330, int(y) + 100).name().upper() == fill
        assert image.pixelColor(int(x) + 172, int(y)).name().upper() == (accent if i == 5 else edge)
        assert image.pixelColor(int(x) + 1, int(y) + 1).name().upper() == '#1A1212'  # rounded corner
    peak = next(t for t in draws.by_text('11-01') if t['size'] == 44)
    assert peak['color'] == accent and peak['bold']
    assert draws.by_text(ui('weekly_peak'))[0]['geom'].y() > 753  # a card label now, not a chart caption


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
@pytest.mark.parametrize('partial', [False, True])
def test_estimate_note_is_inside_price_card_and_never_elided(qapp, draws, lang, partial):
    from shion.lines import Lines
    ui = Lines(lang).ui
    card = finished_card(lang, partial=partial)
    render_card(card)
    note = ui('weekly_partial' if partial else 'weekly_estimate')
    price_label = draws.one(ui('weekly_price_label'))['geom']
    price = draws.one(f"${card['price']:.2f}")
    card_y, card_x = price_label.y() - 14, price_label.x() - 22
    row2_y = draws.one(ui('weekly_active_days'))['geom'].y() - 14
    parts = [t for t in draws.texts if t['geom'].x() == card_x + 22 and t['geom'].y() > price['geom'].y() + 40
             and t['geom'].y() < row2_y and t['size'] == 28]
    assert 1 <= len(parts) <= 2
    assert ''.join(p['text'] for p in parts).replace(' ', '') == note.replace(' ', '')
    assert all(p['geom'].bottom() <= row2_y - 20 - 8 for p in parts)  # inside the card, with padding
    assert price['geom'].y() > card_y and '…' not in ''.join(p['text'] for p in parts)


def test_counter_cards_appear_only_when_shion_recorded_something(qapp, draws):
    from shion.lines import Lines
    ui = Lines('en').ui
    render_card(finished_card('en'))
    keys = ['weekly_chip_tasks', 'weekly_chip_hours', 'weekly_chip_approvals', 'weekly_chip_denials',
            'weekly_chip_pats', 'weekly_chip_snacks']
    chips = [draws.one(ui(k))['geom'] for k in keys]
    assert len({round(c.y()) for c in chips}) == 1 and chips == sorted(chips, key=lambda c: c.x())
    assert chips[0].y() > draws.one(ui('weekly_active_days'))['geom'].y()
    draws.texts.clear()
    render_card(finished_card('en', has_stats=False))
    assert not any(t['text'] == ui('weekly_chip_tasks') for t in draws.texts)


def test_bars_are_wide_rounded_on_top_and_peak_number_is_bold_accent(qapp, draws):
    from shion.lines import Lines
    from shion.weekly_ui import BAR_W, CHART_BASE, bar_x
    card = finished_card()
    image = render_card(card)
    assert BAR_W == 118
    x = bar_x(6)
    mid = int(x + 59)
    assert image.pixelColor(mid, CHART_BASE - 10).name().upper() == '#F4772E'
    assert image.pixelColor(int(x) + 2, CHART_BASE - 10).name().upper() == '#F4772E'
    assert image.pixelColor(int(x) - 4, CHART_BASE - 10).name().upper() == '#1A1212'
    top = CHART_BASE - 1
    while image.pixelColor(mid, top - 1).name().upper() == '#F4772E':
        top -= 1
    assert image.pixelColor(int(x) + 1, top).name().upper() != '#F4772E'  # rounded corner
    peak_number = draws.one(number(card['daily'][6], 'zh'))
    assert peak_number['bold'] and peak_number['color'] == '#F4772E'
    other = draws.one(number(card['daily'][5], 'zh'))
    assert not other['bold'] and other['color'] == '#F2EDEA'
    assert len(draws.by_text(Lines('zh').ui('weekly_peak'))) == 1  # no separate chart caption


def test_footer_has_link_left_and_name_right_and_link_follows_branding_switch(qapp, draws):
    render_card(finished_card())
    link, name = draws.one('github.com/iLLyaaaaaa/shion'), draws.one('诗音 · Shion')
    assert link['geom'].x() == 64 and name['geom'].right() == 1136 and link['geom'].y() == name['geom'].y()
    draws.texts.clear()
    render_card(finished_card(), branding=False)
    assert not draws.by_text('github.com/iLLyaaaaaa/shion') and draws.by_text('诗音 · Shion')


def crowded_cards(lang):
    start = date(2026, 10, 26)
    stats = {str(start + timedelta(days=i)): dict(tasks=12, seconds=7000, approvals=88, denials=3, pats=61,
                                                  snacks=40, seven_day_peak=96) for i in range(7)}
    usage = {'days': {str(start + timedelta(days=i)): {
        'claude-sonnet-5-5': {'0': dict(zip(FIELDS, (25000, 900000 + i * 2000000, 40000, 5000, 200000000 + i * 90000000)))},
        'claude-haiku-9-9': {'0': dict.fromkeys(FIELDS, 1000)}} for i in range(7)}, 'activity': {str(start): 1301}}
    finished = report(start, stats, usage, lang, True, today=date(2026, 11, 3))
    ongoing_start = date(2026, 11, 2)
    ongoing = report(ongoing_start, {str(ongoing_start + timedelta(days=i)): v for i, v in enumerate(stats.values())},
                     {'days': {str(ongoing_start + timedelta(days=i)): v for i, v in enumerate(usage['days'].values())},
                      'activity': {}}, lang, True, today=date(2026, 11, 3))
    off = report(start, stats, usage, lang, False, today=date(2026, 11, 3))
    return [finished, ongoing, off, {**finished, 'has_stats': False}, {**finished, 'title': {**finished['title'],
            'comment': finished['title']['comment'] * 3}}]


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
def test_nothing_overflows_or_gets_elided_in_any_language(qapp, draws, lang):
    for index, card in enumerate(crowded_cards(lang)):
        draws.texts.clear()
        render_card(card)
        for item in draws.texts:
            geometry = item['geom']
            assert item['size'] >= 28
            if hasattr(geometry, 'width'):
                assert item['advance'] <= geometry.width() + 1, item['text']
                assert geometry.left() >= 0 and geometry.right() <= 1200 and geometry.bottom() <= 1500
        # Comments legitimately contain "……"; every other string must be drawn whole.
        assert not [t['text'] for t in draws.texts if t['size'] != 34 and '…' in t['text']]
        comment = [t['text'] for t in draws.texts if t['size'] == 34]
        if index == 4:  # The deliberately over-long comment is cut on its second line only.
            assert len(comment) == 2 and comment[1].endswith('…') and not comment[0].endswith('…')


def test_hero_fonts_use_real_bold_faces_only_for_title_and_total(qapp, draws):
    from shion.weekly_ui import card_font
    zh, en, ja = (card_font(lang, 128, True, hero=True) for lang in ('zh', 'en', 'ja'))
    assert zh.bold() and zh.families()[0] == 'Microsoft YaHei'
    assert en.bold() and en.families()[0] == 'Segoe UI'
    assert ja.families() == ['Yu Gothic UI', 'Yu Gothic', 'Microsoft YaHei', 'Consolas']
    assert card_font('en', 28).families()[0] == 'Microsoft YaHei'  # ordinary text is unchanged
    for lang, family in (('zh', 'Microsoft YaHei'), ('en', 'Segoe UI')):
        draws.texts.clear()
        card = finished_card(lang)
        render_card(card)
        total = draws.one(number(card['totals']['total_tokens'], lang))
        title = draws.one(card['title']['name'])
        assert total['bold'] and title['bold'] and total['family'] == title['family'] == family


def test_comment_breaks_evenly_without_tiny_last_lines(qapp):
    from shion.lines import Lines
    from shion.weekly_ui import NO_LINE_START, card_font, ensure_fonts, wrap_lines
    ensure_fonts()
    zh = card_font('zh', 34)
    assert wrap_lines(zh, '这周的 token 一口一口全吃光啦，好能吃！', 620, 2) == ['这周的 token 一口一口', '全吃光啦，好能吃！']
    assert wrap_lines(zh, '这周也一起走过来了，辛苦啦！', 620, 2) == ['这周也一起走过来了，辛苦啦！']
    rules = json.loads((Path(__file__).parents[1] / 'assets/weekly_titles.json').read_text(encoding='utf-8'))
    for lang in ('zh', 'en', 'ja'):
        font = card_font(lang, 34)
        for rule in rules:
            comment = rule['comment'][lang]
            lines = wrap_lines(font, comment, 620, 2)
            assert 1 <= len(lines) <= 2 and ''.join(lines).replace(' ', '') == comment.replace(' ', '')
            assert all(__import__('PySide6.QtGui', fromlist=['QFontMetrics']).QFontMetrics(font).horizontalAdvance(l) <= 620
                       for l in lines)
            if len(lines) == 2:
                assert len(lines[1].replace(' ', '')) >= 3 and lines[1][0] not in NO_LINE_START
                if lang == 'en':
                    assert ' '.join(lines) == comment  # never splits inside a word


def test_forty_pixel_gap_between_comment_and_total_label(qapp):
    from PySide6.QtGui import qGray
    card = finished_card()
    card['title'] = {**card['title'], 'comment': '这周的 token 一口一口全吃光啦，好能吃！'}  # two lines
    image = render_card(card)
    inked = [y for y in range(360, 540)
             if any(qGray(image.pixelColor(x, y).rgb()) > 100 for x in range(64, 560, 2))]
    runs, start = [], inked[0]
    for before, after in zip(inked, inked[1:] + [None]):
        if after != before + 1:
            runs.append((start, before))
            start = after
    assert len(runs) >= 2
    gap = runs[-1][0] - runs[-2][1]  # last comment line to the "total" label glyphs
    assert 36 <= gap <= 54, runs


def test_busiest_day_card_and_highlighted_bar_always_agree(qapp, draws):
    from shion.weekly_ui import CHART_BASE, bar_center
    start = date(2026, 11, 2)
    today = date(2026, 11, 4)
    usage = usage_for(start, [100, 300, 900, 0, 0, 0, 0])  # today (Wednesday) is the largest day
    card = report(start, {}, usage, 'zh', True, today=today)
    image = render_card(card)
    lit = [i for i in range(7) if image.pixelColor(int(bar_center(i)), CHART_BASE - 3).name().upper() == '#F4772E']
    counted = card['daily'][:card['days_elapsed']]
    assert lit == [card['peak_day']] == [counted.index(max(counted))] == [2]
    value = next(t for t in draws.texts if t['size'] == 44 and t['color'] == '#F4772E')
    assert value['text'] == (start + timedelta(days=2)).strftime('%m-%d')
    # A finished week also agrees.
    finished = report(start, {}, usage, 'zh', True, today=date(2026, 11, 10))
    image = render_card(finished)
    lit = [i for i in range(7) if image.pixelColor(int(bar_center(i)), CHART_BASE - 3).name().upper() == '#F4772E']
    assert lit == [finished['peak_day']]


def test_weekly_title_label_is_hidden_while_the_week_is_unfinished(qapp, draws):
    from shion.lines import Lines
    start = date(2026, 11, 2)
    ongoing = report(start, {}, usage_for(start, [5] * 7), 'zh', True, today=date(2026, 11, 3))
    render_card(ongoing)
    assert not draws.by_text(Lines('zh').ui('weekly_title_label')) and draws.by_text('本周进行中 · 第 2 天')
    draws.texts.clear()
    render_card(finished_card())
    assert draws.by_text(Lines('zh').ui('weekly_title_label'))


def test_english_labels_are_uppercase_and_estimate_wording(qapp, draws):
    from shion.lines import Lines
    ui = Lines('en').ui
    labels = ['weekly_title_label', 'weekly_total', 'weekly_output', 'weekly_price_label', 'weekly_daily_avg',
              'weekly_active_days', 'weekly_latest_label', 'weekly_peak', 'weekly_chart', 'weekly_chip_tasks',
              'weekly_chip_hours', 'weekly_chip_approvals', 'weekly_chip_denials', 'weekly_chip_pats',
              'weekly_chip_snacks']
    assert all(ui(k).isupper() for k in labels), [ui(k) for k in labels if not ui(k).isupper()]
    assert ui('weekly_peak') == 'HARDEST DAY' and ui('weekly_estimate') == 'Estimate only'
    assert ui('weekly_partial').startswith('Estimate only')
    render_card(finished_card('en'))
    assert draws.one('HARDEST DAY') and draws.one('Estimate only')


@pytest.mark.parametrize('lang', ['zh', 'en', 'ja'])
@pytest.mark.parametrize('partial', [False, True])
def test_first_row_cards_have_equal_height(qapp, lang, partial):
    image = render_card(finished_card(lang, partial=partial))
    bottoms = []
    for column in range(3):
        x = 64 + column * 364 + 330
        bottoms.append(next(y for y in range(800, 1000) if image.pixelColor(x, y).name().upper() == '#33241F'))
    assert len(set(bottoms)) == 1, bottoms


def test_scan_drops_cache_entries_of_deleted_transcripts(tmp_path):
    first, second = tmp_path / 'projects' / 'p' / 'a.jsonl', tmp_path / 'projects' / 'p' / 'b.jsonl'
    write(first, [row('a')])
    write(second, [row('b', stamp='2026-11-02T07:00:00Z')])
    s = scanner(tmp_path)
    s.scan(TODAY)
    assert len(json.loads((tmp_path / 'cache.json').read_text(encoding='utf-8'))['files']) == 2
    second.unlink()
    result = s.scan(TODAY)
    assert len(result['files']) == 1
    assert len(json.loads((tmp_path / 'cache.json').read_text(encoding='utf-8'))['files']) == 1


def _out_total(result):
    return sum(c.get('out', 0) for models in result['days'].values() for tiers in models.values() for c in tiers.values())


def test_unreadable_transcript_is_skipped_without_failing_the_scan(tmp_path, monkeypatch):
    s = scanner(tmp_path)
    good, locked = tmp_path / 'projects/a/good.jsonl', tmp_path / 'projects/b/locked.jsonl'
    write(good, [row('g', out=5)])
    write(locked, [row('l', out=7)])
    real = Path.open
    def guarded(self, *args, **kwargs):
        if self.name == 'locked.jsonl':
            raise PermissionError('locked by another program')
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    first = s.scan(TODAY)
    assert _out_total(first) == 5 and s.skipped == 1
    monkeypatch.setattr(Path, 'open', real)
    again = s.scan(TODAY)
    assert _out_total(again) == 12 and s.skipped == 0
    assert _out_total(s.scan(TODAY)) == 12  # No double counting once it is readable.


def test_unreadable_known_transcript_keeps_its_previous_totals(tmp_path, monkeypatch):
    s = scanner(tmp_path)
    path = tmp_path / 'projects/a/t.jsonl'
    write(path, [row('a', out=5)])
    assert _out_total(s.scan(TODAY)) == 5
    real = Path.open
    monkeypatch.setattr(Path, 'open', lambda self, *a, **k: (_ for _ in ()).throw(PermissionError('x'))
                        if self.name == 't.jsonl' else real(self, *a, **k))
    assert _out_total(s.scan(TODAY)) == 5 and s.skipped == 1


def test_read_error_mid_scan_keeps_the_old_cache(tmp_path, monkeypatch):
    s = scanner(tmp_path)
    write(tmp_path / 'projects/a/t.jsonl', [row('a', out=5)])
    s.scan(TODAY)
    before = (tmp_path / 'cache.json').read_bytes()
    write(tmp_path / 'projects/a/t.jsonl', [row('b', out=6)], mode='a')
    def broken(*args, **kwargs):
        raise OSError('disk error')
    monkeypatch.setattr(s, '_read', broken)
    assert s.scan(TODAY) is None
    assert (tmp_path / 'cache.json').read_bytes() == before


@pytest.mark.parametrize('rules', ['missing', 'broken', [{'priority': 0, 'all': [{'field': 'tasks'}]}], [], 'no-strings'])
def test_bad_title_table_falls_back_instead_of_crashing(tmp_path, monkeypatch, rules):
    from shion import weekly
    if rules in ('missing', 'broken'):
        monkeypatch.setattr(weekly, 'ROOT', tmp_path)
        if rules == 'broken':
            (tmp_path / 'assets').mkdir()
            (tmp_path / 'assets/weekly_titles.json').write_text('{oops', encoding='utf-8')
        rules = None
    elif rules == 'no-strings':
        rules = [{'priority': 0, 'name': {'en': 1}, 'comment': {'en': 'x'}, 'sprite': 'done'}]
    for lang, name in (('zh', '勤劳搭档'), ('en', 'Steady Partner'), ('ja', '働き者の相棒')):
        title = title_for({'tasks': 3}, lang, rules)
        assert title['name'] == name and title['sprite'] == 'done'
