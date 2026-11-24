from concurrent.futures import Future
from datetime import datetime, timedelta
from time import monotonic
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QPushButton

from shion import remote, usage_service
from shion.budget import BudgetReading
from shion.budget_policy import BudgetPolicy
from shion.lines import Lines
from shion.server import ShionServer
from shion.state import SaveData, load
from shion.usage import SYNTHETIC, daily_tokens
from shion.usage_service import DailyReading, UsageService
from shion.weekly import report, week_start
from tests.test_budget_pause import END, GO, HOLD
from tests.test_budget_ui import action
from tests.test_controller import env, qapp  # noqa: F401
from tests.test_remote_control import post
from tests.test_weekly import row, scanner, write

DAY = datetime(2026, 11, 23, 23, 59).date()


def test_midnight_scan_keeps_next_day_records_in_all_sessions_and_subagents(tmp_path):
    scan = scanner(tmp_path)
    before = datetime.combine(DAY, datetime.max.time()).astimezone().isoformat()
    midnight = datetime.combine(DAY + timedelta(days=1), datetime.min.time()).astimezone().isoformat()
    main = scan.projects / 'project' / 'session.jsonl'
    write(main, [row('yesterday', stamp=before), row('today', stamp=midnight)])
    write(main.with_suffix('') / 'subagents' / 'agent.jsonl', [row('agent', stamp=midnight)])
    write(scan.projects / 'other' / 'other.jsonl', [row('other', stamp=midnight),
          row('synthetic', stamp=midnight, model=SYNTHETIC)])
    first = scan.scan(DAY)
    today = DAY + timedelta(days=1)
    assert daily_tokens(first, DAY) == 100
    assert daily_tokens(first, today) == 0
    second = scan.scan(today)
    start = week_start(today)
    assert daily_tokens(second, today) == report(start, {}, second)['daily'][(today - start).days] == 300
    assert daily_tokens(second, DAY) == 100


@pytest.fixture
def controlled_scan(tmp_path, monkeypatch):
    service = UsageService(tmp_path)
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(usage_service, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    starts = []

    def submit(scan, day, cancelled):
        starts.append((clock.now, day))
        return Future()

    monkeypatch.setattr(service.executor, 'submit', submit)
    try:
        yield service, clock, starts
    finally:
        service.close()


def test_active_refresh_is_throttled_and_stop_can_request_an_immediate_followup(controlled_scan):
    service, clock, starts = controlled_scan
    service.data = {'days': {str(DAY): {'model': {'0': {'out': 123}}}}}
    assert service.daily_reading is None  # An on-disk weekly cache is not a fresh reading.
    service.poll(working=True, day=DAY)
    assert starts == [(0, DAY)] and service.daily_reading is None
    service.future.set_result(service.data)
    assert service.poll(working=True, day=DAY)
    assert service.daily_reading.total == 123
    clock.now = 59
    service.poll(working=True, day=DAY)
    assert len(starts) == 1
    clock.now = 60
    service.poll(working=True, day=DAY)
    assert starts[-1] == (60, DAY)
    clock.now = 62
    service.request()  # Stop during an in-flight scan keeps a refresh queued.
    service.poll(working=False, day=DAY)
    assert len(starts) == 2
    service.future.set_result(service.data)
    service.poll(working=False, day=DAY)
    assert starts == [(0, DAY), (60, DAY), (62, DAY)]
    service.future.set_result(None)
    assert not service.poll(working=False, day=DAY)
    assert service.failed and service.daily_reading is None


def test_scan_started_yesterday_cannot_supply_a_daily_reading(controlled_scan):
    service, clock, starts = controlled_scan
    service.poll(working=True, day=DAY)
    next_day = DAY + timedelta(days=1)
    service.future.set_result({'days': {str(DAY): {'model': {'0': {'out': 123}}}}})
    assert service.poll(working=True, day=next_day)  # Still useful to the historical week.
    assert service.daily_reading is None
    clock.now = 60
    service.poll(working=True, day=next_day)
    assert starts[-1] == (60, next_day)
    service.future.set_result({'days': {}})
    service.poll(working=True, day=next_day)
    assert service.daily_reading == DailyReading(next_day, 0, 60)


@pytest.fixture
def daily_server(monkeypatch):
    clock = SimpleNamespace(now=datetime(2026, 11, 23, 23, 59), enabled=True)
    policy = BudgetPolicy(default=100, daily_default=50, clock=lambda: clock.now)
    events = []
    srv = ShionServer(lambda *args: events.append(args), lambda: '', port=0,
                      usage_enabled=lambda: clock.enabled, budget_policy=policy)
    srv.start()
    monkeypatch.setattr(srv._httpd.budget_meter, 'observe', lambda *_: BudgetReading(100, 100, 0, True))
    try:
        yield srv, policy, clock, events
    finally:
        srv.hub.set_link_enabled(False)
        srv.stop()


def checkpoint(srv, session, *, path=None, wait=0):
    body = {'session': session, 'wait': wait}
    if path is not None:
        body['transcript_path'] = path
    return post(srv, '/pause/wait', body)


def test_unknown_or_stale_daily_usage_fails_open_and_logs_only_numbers(daily_server, caplog, monkeypatch):
    srv, policy, clock, _ = daily_server
    caplog.set_level('INFO', logger='shion.budget')
    monkeypatch.setattr(srv._httpd.budget_meter, 'observe', lambda *_: BudgetReading(0, 0, 0, True))
    assert checkpoint(srv, 'first', path='private/sample.jsonl') == GO
    policy.set_daily_reading(DailyReading(DAY - timedelta(days=1), 100, monotonic()))
    assert checkpoint(srv, 'first') == GO
    policy.set_daily_reading(DailyReading(DAY, 50, monotonic() - 14))
    assert checkpoint(srv, 'first') == HOLD
    policy.set_daily_reading(None)  # The next scan failed.
    assert checkpoint(srv, 'second') == GO
    clock.enabled = False
    assert checkpoint(srv, 'second') == GO
    log_lines = [r.getMessage() for r in caplog.records if r.name == 'shion.budget']
    assert len(log_lines) == 4
    assert '今日用量=50 上限=50 数据距今=14.' in log_lines[2]
    assert '今日用量=未知 上限=50 数据距今=未知' in log_lines[0]
    assert log_lines[0] == log_lines[1] == log_lines[3]
    assert 'sample.jsonl' not in caplog.text


def test_one_daily_panel_releases_multiple_sessions_and_session_budget_is_checked_next(daily_server):
    srv, policy, clock, _ = daily_server
    hub = srv.hub
    policy.set_daily_reading(DailyReading(DAY, 50, monotonic()))
    assert checkpoint(srv, 'a', path='synthetic') == HOLD
    assert checkpoint(srv, 'b') == HOLD
    holds = hub.budget_pauses()
    assert holds['a'] is holds['b'] and holds['a'].day == DAY
    assert not policy.choose_daily(holds['a'], 50, hub)
    assert policy.choose_daily(holds['a'], 60, hub)
    assert policy.daily_usage().budget == 60
    assert checkpoint(srv, 'a', wait=.01) == GO
    assert checkpoint(srv, 'b', wait=.01) == GO
    assert checkpoint(srv, 'a', path='synthetic') == HOLD
    assert hub.budget_pauses()['a'].day is None


@pytest.mark.parametrize('timeout', [False, True])
def test_end_all_and_timeout_stop_only_the_daily_group(daily_server, timeout):
    srv, policy, _, events = daily_server
    assert checkpoint(srv, 'session-budget', path='synthetic') == HOLD
    srv.hub.pause('manual')
    policy.set_daily_reading(DailyReading(DAY, 100, monotonic()))
    assert checkpoint(srv, 'a') == HOLD
    assert checkpoint(srv, 'b') == HOLD
    if timeout:
        assert post(srv, '/event', {'type': 'pause_timeout', 'session': 'a'}) == (200, {'ok': True})
        assert events[-1] == ('pause_timeout', None, {'session': 'a', 'budget_timeout': True})
    else:
        assert srv.hub.resolve_daily_budget(srv.hub.budget_pauses()['a'], end=True)
    assert checkpoint(srv, 'a', wait=.01) == END
    assert checkpoint(srv, 'b', wait=.01) == END
    assert checkpoint(srv, 'session-budget', wait=.01) == HOLD
    assert checkpoint(srv, 'manual', wait=.01) == HOLD


def test_end_all_reaches_a_session_joining_before_its_first_poll_returns(daily_server, monkeypatch):
    srv, policy, _, _ = daily_server
    monkeypatch.setattr(remote, 'time', SimpleNamespace(monotonic=lambda: 123.0))
    policy.set_daily_reading(DailyReading(DAY, 100, monotonic()))
    assert checkpoint(srv, 'a') == HOLD
    observe = policy.observe

    def join_then_end(session, total, hub, **kwargs):
        joined = observe(session, total, hub, **kwargs)
        assert hub.resolve_daily_budget(hub.budget_pauses()['a'], end=True)
        return joined

    monkeypatch.setattr(policy, 'observe', join_then_end)
    assert checkpoint(srv, 'b') == END
    assert checkpoint(srv, 'a', wait=.01) == END
    assert not srv.hub.budget_pauses()
    monkeypatch.setattr(policy, 'observe', observe)
    assert checkpoint(srv, 'b') == HOLD  # Next checkpoint arrives on the same clock tick.
    assert checkpoint(srv, 'b', wait=.01) == HOLD


def test_today_unlimited_expires_at_local_midnight_even_after_reload(daily_server):
    srv, policy, clock, _ = daily_server
    policy.set_daily_reading(DailyReading(DAY, 100, monotonic()))
    assert checkpoint(srv, 'still-running') == HOLD
    assert policy.choose_daily(srv.hub.budget_pauses()['still-running'], None, srv.hub)
    data = SaveData.from_dict(SaveData(daily_budget_default=50, daily_budget=policy.daily_state).to_dict())
    restored = BudgetPolicy(daily_default=data.daily_budget_default, daily=data.daily_budget, clock=lambda: clock.now)
    assert restored.daily_usage().budget is None
    assert checkpoint(srv, 'still-running') == GO
    clock.now += timedelta(minutes=1)
    assert restored.daily_usage().budget == policy.daily_usage().budget == 50
    assert policy.daily_usage().total is None
    assert checkpoint(srv, 'still-running') == GO
    policy.set_daily_reading(DailyReading(clock.now.date(), 50, monotonic()))
    assert checkpoint(srv, 'still-running') == HOLD
    assert srv.hub.budget_pauses()['still-running'].day == clock.now.date()


def test_midnight_releases_a_daily_hold_from_yesterday(daily_server):
    srv, policy, clock, _ = daily_server
    policy.set_daily_reading(DailyReading(DAY, 100, monotonic()))
    assert checkpoint(srv, 'still-running') == HOLD
    clock.now += timedelta(minutes=1)
    assert checkpoint(srv, 'still-running') == GO
    assert not srv.hub.budget_pauses()


def publish(env, total):
    env.ctl.usage.daily_reading = DailyReading(env.now.date(), total, monotonic())
    env.ctl._poll_usage(env.now)


def test_stop_immediately_schedules_a_background_scan(env, monkeypatch):
    calls = []

    def submit(scan, day, cancelled):
        calls.append(day)
        return Future()

    monkeypatch.setattr(env.ctl.usage.executor, 'submit', submit)
    env.ctl.handle_event('stop', meta={'session': 'a'})
    assert calls == [env.now.date()] and env.ctl.usage.daily_reading is None


@pytest.mark.parametrize('lang, name, paused, used, excluded, custom_value', [
    ('zh', '诗音', '已暂停 {count} 个会话', 'CC 今日已用 5030万 / 5000万', '5000万', '5029'),
    ('en', 'Shion', 'Paused sessions: {count}', 'CC usage today 50.3M / 50M', '50M', '50.29'),
    ('ja', '詩音', '一時停止中のセッション {count} 件', 'CC 今日の使用量 5030万 / 5000万', '5000万', '5029'),
])
def test_single_daily_panel_buttons_and_tray_tooltip(env, lang, name, paused, used, excluded, custom_value):
    ctl = env.ctl
    env.win.show()
    ctl.lines = Lines(lang)
    ui = ctl.lines.ui
    ctl.set_daily_budget(50_000_000)
    publish(env, 50_300_000)
    for count, session in enumerate(('a', 'b'), start=1):
        assert ctl.budget_policy.observe(session, None, ctl.hub)
        ctl.hub.wait_gate(0, session)
        ctl.handle_event('budget_pause', meta={'session': session})
        panel = ctl._checkpoint
        assert panel.layout().itemAt(1).widget().text() == paused.format(count=count)
    env.advance(1)
    assert panel.isVisible() and panel.rows == []
    assert panel._title.text() == used
    assert ctl.tray_tooltip() == f'{name}\n{used}'
    buttons = [button for button in panel.findChildren(QPushButton) if button.isVisible()]
    by_text = {button.text(): button for button in buttons}
    assert len(by_text) == len(buttons) == 5
    assert excluded not in by_text
    by_text[ui('budget_custom')].click()
    dialog = panel._budget_input[2]
    dialog.setTextValue(custom_value)
    dialog.accept()
    assert dialog.isVisible() and dialog.labelText() == ui('budget_daily_too_low')
    dialog.reject()
    by_text[ui('budget_daily_unlimited')].click()
    assert not ctl.hub.budget_pauses()
    assert ctl.tray_tooltip().endswith(ui('budget_unlimited'))


@pytest.mark.parametrize('lang, name, pending', [
    ('zh', '诗音', 'CC 今日用量统计中…'),
    ('en', 'Shion', 'Calculating CC usage today…'),
    ('ja', '詩音', 'CC 今日の使用量を集計中…'),
])
def test_tray_tooltip_while_daily_usage_is_unknown(env, monkeypatch, lang, name, pending):
    ctl = env.ctl
    ctl.set_language(lang)
    expected = f'{name}\n{pending}'
    scans = [Future(), Future()]
    submits = iter(scans)
    monkeypatch.setattr(ctl.usage.executor, 'submit', lambda *_: next(submits))

    ctl.usage.request()
    ctl._poll_usage(env.now)
    assert ctl.usage.future is scans[0] and not scans[0].done()
    assert ctl.tray_tooltip() == expected

    scans[0].set_result({'days': {}})
    ctl._poll_usage(env.now)
    assert ' 0 / ' in ctl.tray_tooltip()

    ctl.usage.request()
    ctl._poll_usage(env.now)
    scans[1].set_exception(OSError())
    ctl._poll_usage(env.now)
    assert ctl.tray_tooltip() == expected

    publish(env, 123)
    env.now += timedelta(days=1)
    ctl._poll_usage(env.now)
    assert ctl.tray_tooltip() == expected

    ctl.set_usage_enabled(False)
    assert ctl.tray_tooltip() == name


def test_daily_budget_is_grey_and_turning_statistics_off_releases_daily_pauses(env):
    ctl = env.ctl
    ui = ctl.lines.ui
    assert env.data.daily_budget_default is None
    ctl.set_daily_budget(50_000_000)
    publish(env, 50_300_000)
    assert ctl.budget_policy.observe('a', None, ctl.hub)
    ctl.set_usage_enabled(False)
    menu = ctl.build_menu()
    settings = action(menu, ui('menu_settings')).menu()
    daily = action(settings, ui('budget_daily'))
    assert not daily.isEnabled()
    assert all(not preset.isEnabled() for preset in daily.menu().actions())
    assert ctl.tray_tooltip() == '诗音'
    assert ctl.budget_policy.daily_usage().total is None
    assert not ctl.hub.budget_pauses()


def test_end_all_button_ends_both_daily_pauses(env):
    ctl = env.ctl
    env.win.show()
    ctl.set_daily_budget(50)
    publish(env, 50)
    for session in ('a', 'b'):
        assert ctl.budget_policy.observe(session, None, ctl.hub)
        assert ctl.hub.wait_gate(0, session) == (True, False)
        ctl.handle_event('budget_pause', meta={'session': session})
    env.advance(1)
    button, = [b for b in ctl._checkpoint.findChildren(QPushButton)
               if b.isVisible() and b.text() == ctl.lines.ui('budget_daily_end')]
    button.click()
    assert ctl.hub.wait_gate(.01, 'a') == ctl.hub.wait_gate(.01, 'b') == (False, True)


def test_daily_warning_once_per_day_and_budget_including_across_restart(env):
    ctl = env.ctl
    ctl.lines = Lines('en')
    ctl.set_daily_budget(50_000_000)
    for total in (39_999_999, 40_000_000, 41_000_000):
        publish(env, total)
        ctl._speech.dismiss()
        ctl._try_budget_warning()
    assert env.said == ["CC has used 80% of today's limit (40M / 50M)."]
    ctl.set_daily_budget(100_000_000)
    publish(env, 80_000_000)
    ctl._speech.dismiss()
    ctl._try_budget_warning()
    assert env.said[-1] == "CC has used 80% of today's limit (80M / 100M)."
    env.scheduler.flush()
    saved = load(env.path)
    policy = BudgetPolicy(daily_default=saved.daily_budget_default, daily=saved.daily_budget, clock=lambda: env.now)
    policy.set_daily_reading(DailyReading(env.now.date(), 81_000_000, monotonic()))
    assert policy.daily_warning(env.now.date()) is None
    env.now += timedelta(days=1)
    policy.set_daily_reading(DailyReading(env.now.date(), 81_000_000, monotonic()))
    assert policy.daily_warning(env.now.date()).budget == 100_000_000
