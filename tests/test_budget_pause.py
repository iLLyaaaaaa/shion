import json
from datetime import datetime, timedelta
from urllib.error import HTTPError

import pytest
from PySide6.QtWidgets import QPushButton

from shion.budget import BudgetReading
from shion.budget_policy import BudgetPolicy
from shion.lines import Lines
from shion.remote import RemoteHub
from shion.server import ShionServer
from shion.state import SaveData, load, save
from tests.test_controller import env, qapp  # noqa: F401
from tests.test_budget import files, row  # noqa: F401
from tests.test_remote_control import post


SESSION = 'session'
FIRST = {'session': SESSION, 'transcript_path': 'transcript', 'wait': 0}
GO = (200, {'paused': False, 'stop': False})
HOLD = (200, {'paused': True, 'stop': False})
END = (200, {'paused': False, 'stop': True})


@pytest.fixture
def service(monkeypatch):
    policy = BudgetPolicy(100)
    events = []
    settings = {'enabled': True, 'reading': BudgetReading(100, 100, 0, True)}
    srv = ShionServer(lambda *args: events.append(args), lambda: '', port=0,
                      usage_enabled=lambda: settings['enabled'], budget_policy=policy)
    srv.start()
    monkeypatch.setattr(srv._httpd.budget_meter, 'observe', lambda *_: settings['reading'])
    try:
        yield srv, policy, events, settings
    finally:
        srv.hub.set_link_enabled(False)
        srv.stop()


@pytest.mark.parametrize('total,complete,enabled,expected', [
    (99, True, True, GO), (100, True, True, HOLD), (101, True, True, HOLD),
    (100_000_000, True, True, HOLD), (100, False, True, HOLD), (99, False, True, GO),
    (None, True, True, GO), (100, True, False, GO),
])
def test_only_first_checkpoint_with_sufficient_known_usage_pauses(service, total, complete, enabled, expected):
    srv, policy, events, settings = service
    settings.update(enabled=enabled, reading=BudgetReading(total, total, 0, complete) if total is not None else None)
    assert post(srv, '/pause/wait', {**FIRST, 'wait': 0.001}) == GO
    assert post(srv, '/pause/wait', FIRST) == expected
    assert events == ([('budget_pause', None, {'session': SESSION})] if expected == HOLD else [])
    assert (policy.take_changes() is None) == (not enabled or total is None)


def test_cleanup_of_budget_pause_cannot_be_spoofed_with_pause_notification(service):
    srv, _, _, _ = service
    with pytest.raises(HTTPError) as refused:
        post(srv, '/event', {'type': 'budget_pause', 'session': SESSION})
    assert refused.value.code == 400
    assert not srv.hub.is_paused


def test_raise_budget_then_exceed_it_and_choose_unlimited(service):
    srv, policy, events, settings = service
    hub = srv.hub
    assert post(srv, '/pause/wait', FIRST) == HOLD
    hold = hub.budget_pauses()[SESSION]
    assert not policy.choose(SESSION, hold, 100, hub)
    assert policy.choose(SESSION, hold, 50_000_000, hub)
    assert post(srv, '/pause/wait', FIRST) == GO
    settings['reading'] = BudgetReading(50_000_001, 50_000_000, 1, True)
    assert post(srv, '/pause/wait', FIRST) == HOLD
    assert not policy.choose(SESSION, hold, None, hub)  # stale button from a previous hold
    assert policy.choose(SESSION, hub.budget_pauses()[SESSION], None, hub)
    assert post(srv, '/pause/wait', FIRST) == GO
    assert policy.take_changes()[SESSION].budget is None
    assert len(events) == 2


def test_manual_stop_first_and_after_budget_preserves_both_reasons(service):
    srv, policy, events, _ = service
    hub = srv.hub
    hub.pause(SESSION)
    assert post(srv, '/pause/wait', FIRST) == HOLD
    assert not events and not hub.budget_pauses()
    hub.resume(SESSION)
    assert post(srv, '/pause/wait', FIRST) == HOLD
    hold = hub.budget_pauses()[SESSION]
    hub.pause(SESSION)
    hub.resume()  # menu Continue only releases the manual reason
    assert hub.budget_pauses()[SESSION] is hold
    hub.pause(SESSION)
    assert policy.choose(SESSION, hold, 50_000_000, hub)
    assert hub.is_session_manually_paused(SESSION)
    assert post(srv, '/pause/wait', FIRST) == HOLD
    hub.resume(SESSION)
    assert post(srv, '/pause/wait', FIRST) == GO


def test_end_between_polls_stops_waiters_but_does_not_reset_budget(service):
    srv, policy, events, _ = service
    assert post(srv, '/pause/wait', FIRST) == HOLD
    srv.hub.end(SESSION)
    assert post(srv, '/pause/wait', {'session': SESSION, 'wait': 1}) == END
    assert events[-1] == ('work_stopped', None, {'session': SESSION})
    assert post(srv, '/pause/wait', {'session': SESSION, 'wait': 0}) == GO
    assert policy.take_changes()[SESSION].budget == 100


def test_budget_timeout_ends_only_its_session(service):
    srv, _, events, _ = service
    assert post(srv, '/pause/wait', FIRST) == HOLD
    srv.hub.pause()  # another manually stopped session must stay stopped
    assert post(srv, '/pause/wait', {'session': 'other', 'wait': 0}) == HOLD
    assert post(srv, '/event', {'type': 'pause_timeout', 'session': SESSION}) == (200, {'ok': True})
    assert events[-1] == ('pause_timeout', None, {'session': SESSION, 'budget_timeout': True})
    assert post(srv, '/pause/wait', {'session': SESSION, 'wait': 1}) == END
    assert post(srv, '/pause/wait', {'session': 'other', 'wait': 0}) == HOLD


def test_subagent_tokens_trigger_parent_budget(files):
    main, child = files
    main.write_bytes(row('parent'))
    child.parent.mkdir(parents=True)
    child.write_bytes(row('child'))
    srv = ShionServer(lambda *_: None, lambda: '', port=0, budget_policy=BudgetPolicy(36))
    srv.start()
    try:
        assert post(srv, '/pause/wait', {**FIRST, 'transcript_path': str(main)}) == HOLD
        assert srv.hub.budget_pauses()[SESSION].total == 36
    finally:
        srv.stop()


def test_defaults_are_copied_once_and_seven_days_of_inactivity_expires(tmp_path):
    now = datetime(2026, 11, 23)
    data = SaveData()
    hub = RemoteHub()
    policy = BudgetPolicy(data.task_budget_default, data.session_budgets, clock=lambda: now)
    assert not policy.observe('unlimited', 1_000, hub)
    policy.set_default(100)
    assert not policy.observe('unlimited', 1_000, hub)
    assert not policy.observe('old', 99, hub)
    policy.set_default(200)
    assert not policy.observe('new', 150, hub)
    data.task_budget_default = 200
    data.session_budgets = policy.take_changes()
    path = tmp_path / 'state.json'
    save(path, data)
    restored = load(path)
    assert restored.session_budgets == data.session_budgets
    policy = BudgetPolicy(restored.task_budget_default, restored.session_budgets, clock=lambda: now)
    assert policy.observe('old', 100, hub)
    now += timedelta(days=6)
    policy.touch('new')
    now += timedelta(days=1)
    assert set(policy.take_changes()) == {'new'}
    hub.end('old')
    assert not policy.observe('old', 199, hub)  # expired session gets the current default


@pytest.mark.parametrize('lang,custom,unlimited,too_low,high,lower_tier', [
    ('zh', '自定义', '不限', '必须大于', '1021', '1000万'),
    ('en', 'Custom', 'Unlimited', 'must exceed', '10.21', '10M'),
    ('ja', 'カスタム', '無制限', '上回る', '1021', '1000万'),
])
def test_budget_panel_filters_tiers_explains_manual_pause_and_rejects_small_custom(
    env, lang, custom, unlimited, too_low, high, lower_tier,
):
    ctl = env.ctl
    ctl.lines = Lines(lang)
    env.win.show()
    ctl.budget_policy.set_default(10_000_000)
    assert ctl.budget_policy.observe(SESSION, 10_200_000, ctl.hub)
    assert ctl.hub.wait_gate(0, SESSION) == (True, False)
    ctl.stop_work(SESSION)
    ctl.handle_event('budget_pause', meta={'session': SESSION})
    env.advance(1)
    panel = ctl._checkpoint
    assert panel.isVisible() and not env.win.paused_badge_shown
    assert panel._budgets[SESSION][1] is True
    buttons = {b.text(): b for b in panel.findChildren(QPushButton)}
    assert lower_tier not in buttons and unlimited in buttons
    buttons[custom].click()
    dialog = panel._budget_input[2]
    dialog.setTextValue('1')
    dialog.accept()
    assert dialog.isVisible() and too_low in dialog.labelText()
    dialog.setTextValue(high)
    dialog.accept()
    assert not ctl.hub.budget_pauses()
    assert ctl.hub.is_session_manually_paused(SESSION)
    assert env.win.paused_badge_shown
    ctl.resume_work(SESSION)
    env.scheduler.flush()
    assert json.loads(env.path.read_text(encoding='utf-8'))['session_budgets'][SESSION]['budget'] == 10_210_000
