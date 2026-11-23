from datetime import date
import json
import os
from pathlib import Path
import threading
from time import perf_counter

import pytest

from shion import budget
from shion.budget import BudgetMeter, BudgetReading
from shion.server import ShionServer
from shion.usage import MAX_LINE, SYNTHETIC, UsageScanner
from tests.test_remote_control import post


def row(mid, output=5, stamp='2026-11-23T05:00:00Z', model='claude-sonnet-4-6', request='req'):
    return json.dumps({
        'type': 'assistant', 'timestamp': stamp, 'requestId': request,
        'message': {'id': mid, 'model': model, 'content': 'PRIVATE_CONTENT', 'usage': {
            'input_tokens': 1, 'output_tokens': output, 'cache_creation_input_tokens': 5,
            'cache_read_input_tokens': 7, 'cache_creation': {
                'ephemeral_5m_input_tokens': 2, 'ephemeral_1h_input_tokens': 3,
            },
        }},
    }).encode() + b'\n'


@pytest.fixture
def files(tmp_path, monkeypatch):
    # Use the production default in the deadline tests below.
    monkeypatch.setattr(budget, 'READ_BUDGET', 2)
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path))
    main = tmp_path / 'projects' / 'Project' / 'session.jsonl'
    main.parent.mkdir(parents=True)
    child = main.with_suffix('') / 'subagents' / 'agent-1.jsonl'
    return main, child


def append(path, data):
    with path.open('ab') as stream:
        stream.write(data)


def test_incremental_stream_updates_and_late_subagent_match_weekly(files, tmp_path):
    main, child = files
    meter = BudgetMeter()
    line = row('one')
    main.write_bytes(line[:-1])
    assert meter.observe('session', main) == BudgetReading(0, 0, 0, True)
    append(main, line[-1:])
    assert meter.observe('session', main) == BudgetReading(18, 18, 0, True)
    append(main, row('one', 19) + row('one', 4) + row('one', 3, request='different'))
    append(main, row('synthetic', 100, model=SYNTHETIC))
    assert meter.observe('session', main) == BudgetReading(48, 48, 0, True)
    child.parent.mkdir(parents=True)
    child.write_bytes(row('one', 22) + row('two', 8))
    assert meter.observe('session', main) == BudgetReading(72, 16, 56, True)
    scanner = UsageScanner(tmp_path / 'usage.json')
    result = scanner.scan(date(2026, 11, 23))
    total = sum(sum(counts.values()) for models in result['days'].values()
                for model, tiers in models.items() if model != SYNTHETIC for counts in tiers.values())
    assert total == meter.observe('session', main).total


@pytest.mark.parametrize('replace', [False, True])
def test_transcript_rewrite_rebuilds_session(files, replace):
    main, child = files
    main.write_bytes(row('one'))
    child.parent.mkdir(parents=True)
    child.write_bytes(row('two'))
    meter = BudgetMeter()
    assert meter.observe('session', main).total == 36
    if replace:
        replacement = main.with_suffix('.tmp')
        replacement.write_bytes(row('new'))
        os.replace(replacement, main)
    else:
        main.write_bytes(b'')
    assert meter.observe('session', main).total == (36 if replace else 18)
    append(main, row('one', 10))
    assert meter.observe('session', main).total == (59 if replace else 41)


def test_oversized_line_and_old_usage(files):
    main, _ = files
    main.write_bytes(b'x' * (MAX_LINE + 4))
    meter = BudgetMeter()
    assert meter.observe('session', main).total == 0
    append(main, b'\n' + row('old', stamp='2025-11-22T05:00:00Z'))
    assert meter.observe('session', main).total == 18


def test_rejects_outside_traversal_wrong_name_and_relative_path(files, tmp_path):
    main, _ = files
    main.write_bytes(row('one'))
    outside = tmp_path / 'projects-old' / main.name
    outside.parent.mkdir()
    outside.write_bytes(row('one'))
    meter = BudgetMeter()
    assert meter.observe('session', outside) is None
    assert meter.observe('session', main.parent / '..' / main.parent.name / main.name) is None
    assert meter.observe('other', main) is None
    assert meter.observe('session', Path(main.name)) is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows path semantics')
def test_windows_drive_and_directory_case(files):
    main, _ = files
    main.write_bytes(row('one'))
    assert BudgetMeter().observe('session', str(main).swapcase()).total == 18


@pytest.mark.parametrize('target', ['main', 'parent', 'child'])
def test_rejects_links(files, tmp_path, target):
    main, child = files
    source = tmp_path / 'source'
    source.mkdir()
    transcript = source / main.name
    transcript.write_bytes(row('one'))
    try:
        if target == 'main':
            main.symlink_to(transcript)
        elif target == 'parent':
            link = main.parent.parent / 'Linked'
            link.symlink_to(source, target_is_directory=True)
            main = link / main.name
        else:
            main.write_bytes(row('one'))
            child.parent.mkdir(parents=True)
            child.symlink_to(transcript)
    except OSError as error:
        if os.name == 'nt' and error.winerror in (5, 1314):
            pytest.skip('Windows symlink creation requires permission')
        raise
    assert BudgetMeter().observe('session', main) is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows junctions')
def test_rejects_subagent_junction(files, tmp_path):
    import _winapi

    main, child = files
    main.write_bytes(row('one'))
    child.parent.parent.mkdir()
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    (outside / child.name).write_bytes(row('two'))
    _winapi.CreateJunction(str(outside), str(child.parent))
    try:
        assert BudgetMeter().observe('session', main) is None
    finally:
        child.parent.rmdir()


def test_expiration_releases_state_and_recreates_totals(files, monkeypatch):
    main, _ = files
    main.write_bytes(row('one'))
    other = main.with_name('other.jsonl')
    other.write_bytes(row('two', 8))
    clock = [25.0]
    monkeypatch.setattr(budget, 'monotonic', lambda: clock[0])
    meter = BudgetMeter()
    assert meter.observe('session', main).total == 18
    inactive = meter._sessions['session']
    clock[0] += budget.SESSION_TTL
    assert meter.observe('other', other).total == 21
    assert meter._sessions['session'] is inactive
    active = meter._sessions['other']
    clock[0] += 1
    assert meter.observe('other', other).total == 21
    assert 'session' not in meter._sessions
    assert meter._sessions['other'] is active
    assert meter.observe('session', main).total == 18
    assert meter._sessions['session'] is not inactive


def test_read_error_returns_unknown_and_can_retry(files, monkeypatch):
    main, _ = files
    main.write_bytes(row('one'))
    meter = BudgetMeter()

    def locked(*args):
        raise PermissionError

    with monkeypatch.context() as patch:
        patch.setattr(meter, '_open', locked)
        assert meter.observe('session', main) is None
    assert meter.observe('session', main).total == 18


def test_blocked_io_returns_partial_then_resumes_at_checkpoint(files, monkeypatch):
    main, _ = files
    main.write_bytes(row('one'))
    meter = BudgetMeter()
    assert meter.observe('session', main).total == 18
    append(main, row('two'))
    release = threading.Event()
    opened = meter._open
    opens = []

    def block_read(path, info):
        opens.append(path)
        if len(opens) == 2:  # Block after validation and the first snapshot.
            release.wait(2)
        return opened(path, info)

    with monkeypatch.context() as patch:
        patch.setattr(meter, '_open', block_read)
        patch.setattr(budget, 'READ_BUDGET', 0.05)
        try:
            start = perf_counter()
            assert meter.observe('session', main) == BudgetReading(18, 18, 0, False)
            assert perf_counter() - start < 0.3
            pending = meter._sessions['session'].pending
            assert meter.observe('session', main) == BudgetReading(18, 18, 0, False)
            assert len(opens) == 2
        finally:
            release.set()
        assert pending.done.wait(2)
    assert meter.observe('session', main) == BudgetReading(36, 36, 0, True)


def test_pause_wait_logs_measurements_only_when_enabled_and_preserves_gate(files, caplog, monkeypatch):
    main, _ = files
    main.write_bytes(row('one'))
    enabled = False
    server = ShionServer(lambda *args: None, lambda: '', port=0, usage_enabled=lambda: enabled)
    request = {'session': 'session', 'transcript_path': str(main), 'wait': 0}
    server.start()
    try:
        with caplog.at_level('INFO', logger='shion.server'):
            assert post(server, '/pause/wait', request) == (200, {'paused': False, 'stop': False})
            assert '预算计量' not in caplog.text
            enabled = True
            assert post(server, '/pause/wait', {**request, 'wait': 0.1}) == (200, {'paused': False, 'stop': False})
            assert '预算计量' not in caplog.text
            server.hub.pause('session')
            assert post(server, '/pause/wait', request) == (200, {'paused': True, 'stop': False})
            assert '预算计量 会话session 累计 18（主 18 / 子代理 0）耗时' in caplog.text
            assert str(main) not in caplog.text
            caplog.clear()
            server.hub.resume('session')

            def unreadable(*args):
                raise PermissionError(main)

            meter = server._httpd.budget_meter
            with monkeypatch.context() as patch:
                patch.setattr(meter, '_open', unreadable)
                assert post(server, '/pause/wait', request) == (200, {'paused': False, 'stop': False})
            assert str(main) not in caplog.text
            assert '预算计量' not in caplog.text

            opened = meter._open
            release = threading.Event()

            def slow(*args):
                release.wait(2)
                return opened(*args)

            with monkeypatch.context() as patch:
                patch.setattr(meter, '_open', slow)
                patch.setattr(budget, 'READ_BUDGET', 0.05)
                try:
                    start = perf_counter()
                    assert post(server, '/pause/wait', request) == (200, {'paused': False, 'stop': False})
                    assert perf_counter() - start < 0.5
                    assert '超时，部分结果' in caplog.text
                finally:
                    release.set()
    finally:
        server.stop()
