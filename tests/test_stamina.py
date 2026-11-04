"""Quota tests use synthetic metadata and isolated settings only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from shion.limits import Limits, parse_limits
from hooks import shion_statusline as sl
from hooks import shion_hook as hook
from tools import hooks_config as hc


def sample(value=42, reset=2000, sid='session-a', seven=73):
    data = {'session': sid, 'five_hour': {'used_percentage': value, 'resets_at': reset}}
    if seven is not None:
        data['seven_day'] = {'used_percentage': seven, 'resets_at': reset + 7000}
    return data


@pytest.mark.parametrize('value,level', [(0,0),(49.999,0),(50,1),(79.999,1),(80,2),(94.999,2),(95,3),(130,3)])
def test_terminal_boundaries(value, level):
    limits = Limits()
    limits.update(sample(value), 1000)
    assert limits.level == level


@pytest.mark.parametrize('value', [True, -1, float('nan'), float('inf'), '42', None])
def test_invalid_quota_numbers(value):
    with pytest.raises(ValueError):
        parse_limits(sample(value))


def test_window_missing_and_expiry_do_not_invent_values():
    limits = Limits()
    limits.update(sample(96), 1000)
    limits.acknowledge()
    limits.refresh(2000)
    assert limits.level == 0 and limits.pending[0] == 0
    assert limits.values(2000) == {'five_hour': None, 'seven_day': 73}
    limits.update({'session':'session-a'}, 2000)
    assert limits.values(2000) == {'five_hour':None,'seven_day':None}


def test_speech_once_per_tier_per_window_and_recovery():
    limits = Limits()
    for value in [50, 80, 95]:
        limits.update(sample(value), 1000)
        assert limits.pending[0] == limits.level
        limits.acknowledge()
        limits.update(sample(value), 1001)
        assert limits.pending is None
    limits.update(sample(80), 1002)
    assert limits.pending is None
    limits.update(sample(40), 1003)
    assert limits.pending[0] == 0
    limits.acknowledge()
    limits.update(sample(80), 1004)
    assert limits.pending is None
    limits.update(sample(80, reset=3000), 2001)
    assert limits.pending[0] == 2


def test_two_hook_sessions_recover_independently_without_numeric_quota():
    limits = Limits()
    limits.signal('a', True, 1000)
    assert limits.pending[0] == 3
    limits.acknowledge()
    limits.signal('a', True, 1001)
    assert limits.pending is None
    limits.signal('b', True, 1001)
    limits.signal('a', False, 1002)
    assert limits.level == 3 and limits.pending is None
    limits.signal('b', False, 1003)
    assert limits.level == 0 and limits.pending[0] == 0
    limits.acknowledge()
    limits.signal('a', True, 1004)
    assert limits.pending[0] == 3
    assert all(v is None for v in limits.values(1004).values())


def test_hook_revival_does_not_erase_terminal_data():
    limits=Limits()
    limits.update(sample(99),1000)
    limits.signal('desktop',True,1001)
    limits.signal('desktop',False,1002)
    assert limits.level==3 and limits.values(1002)['five_hour']==99


def test_statusline_payload_allowlist_and_independent_windows():
    raw=json.dumps({'session_id':'s','rate_limits':{'five_hour':{'used_percentage':float('nan'),'resets_at':99},
       'seven_day':{'used_percentage':110,'resets_at':9000,'ignored':'secret'}},'cwd':'secret','transcript_path':'secret','model':'secret'})
    assert sl.payload(raw)=={'session':'s','seven_day':{'used_percentage':110,'resets_at':9000}}


def test_forward_uses_authenticated_existing_transport_and_short_timeout(monkeypatch):
    calls=[]
    monkeypatch.setattr(hook,'request',lambda *a,**k:calls.append((a,k)))
    sl.forward(json.dumps({'session_id':'s','rate_limits':{}}).encode())
    assert calls==[(('/usage/limits',{'session':'s'}),{'timeout':0.3})]


@pytest.mark.parametrize('event,kind,expected', [('StopFailure','rate_limit','quota_down'),
    ('StopFailure','server_error',None),('Notification','quota_auto_resume_fired','quota_revive'),
    ('Notification','quota_auto_resume_stale',None),('Notification','quota_auto_resume_disabled',None)])
def test_hook_signals_have_no_content_or_side_effects(monkeypatch,event,kind,expected):
    sent=[]
    data={'session_id':'s','error':kind,'notification_type':kind,'error_details':'SECRET',
          'last_assistant_message':'SECRET','message':'SECRET','cwd':'SECRET','transcript_path':'SECRET'}
    monkeypatch.setattr(hook,'read_input',lambda:data)
    monkeypatch.setattr(hook,'shion_running',lambda:True)
    monkeypatch.setattr(hook,'session_meta',lambda *a:pytest.fail('broad metadata read'))
    monkeypatch.setattr(hook,'request',lambda *a,**k:sent.append(a))
    monkeypatch.setattr(sys,'argv',['hook',event])
    hook.main()
    assert sent==([('/event',{'type':expected,'session':'s'})] if expected else [])


def test_chain_preserves_exact_stdin_and_stdout(tmp_path):
    script=tmp_path/'original with spaces.py'
    script.write_text('import sys; sys.stdout.buffer.write(b"prefix\\x00"+sys.stdin.buffer.read()+b"\\r\\n")',encoding='utf-8')
    # Write escapes literally in the subprocess source.
    command=subprocess.list2cmdline([sys.executable,str(script)]) if os.name=='nt' else __import__('shlex').join([sys.executable,str(script)])
    record=tmp_path/'record.json'
    record.write_text(json.dumps({'version':1,'original_raw':json.dumps({'type':'command','command':command})}),encoding='utf-8')
    raw=b'{"private":"untouched"}\r\n'
    assert sl.chain(raw,record)==b'prefix\x00'+raw+b'\r\n'
    record.write_text('{}',encoding='utf-8')
    assert sl.chain(raw,record)==b''


def test_chain_timeout_is_bounded(tmp_path,monkeypatch):
    calls=[]
    class Slow:
        def communicate(self,raw=None,timeout=None):
            if timeout is not None:
                calls.append(timeout)
                raise subprocess.TimeoutExpired('test',timeout)
            return b'',None
        def kill(self): calls.append('kill')
    monkeypatch.setattr(sl.subprocess,'Popen',lambda *a,**k:Slow())
    record=tmp_path/'record.json'
    record.write_text(json.dumps({'version':1,'original_raw':json.dumps({'type':'command','command':'ignored'})}),encoding='utf-8')
    assert sl.chain(b'input',record)==b'' and calls==[1,'kill']


def test_statusline_entry_does_not_import_qt(tmp_path):
    record=tmp_path/'none.json'
    code="import sys; from shion.__main__ import main; main(['--statusline','--record',sys.argv[1]]); assert not any(k.startswith('PySide6') for k in sys.modules)"
    result=subprocess.run([sys.executable,'-c',code,str(record)],input=b'{"session_id":"s"}',capture_output=True,timeout=5)
    assert result.returncode==0 and result.stdout==b'' and result.stderr==b''


def test_report_quota_peak_roundtrips_and_selects_title():
    from datetime import date
    from shion.weekly import clean_stats,report
    stats=clean_stats({'2026-11-02':{'seven_day_peak':93.5},'2026-10-26':{'seven_day_peak':99}})
    result=report(date(2026,11,2),stats,{},'en')
    assert result['totals']['seven_day_peak']==93.5 and result['title']['name']=='Quota Assassin'
    assert 'seven_day_peak' not in report(date(2026,11,9),stats,{})['totals']
    assert clean_stats({'2026-11-02':{'seven_day_peak':True}})=={'2026-11-02':{}}


def test_missing_window_hides_stamina_without_claiming_revival():
    limits=Limits()
    limits.update(sample(96),1000)
    limits.acknowledge()
    limits.update({'session':'session-a'},1001)
    assert limits.level==0 and limits.pending is None


def test_multi_session_numeric_values_remain_independent():
    limits=Limits()
    limits.update(sample(96,reset=2000,sid='a'),1000)
    limits.acknowledge()
    limits.update(sample(30,reset=3000,sid='b',seven=None),1001)
    assert limits.level==3 and limits.pending is None
    limits.update({'session':'a'},1002)
    assert limits.level==0 and limits.values(1002)['five_hour']==30


def test_real_statusline_process_relays_to_authenticated_loopback(tmp_path,monkeypatch):
    from shion.server import ShionServer
    events=[]
    srv=ShionServer(lambda *args:events.append(args),lambda:'',port=0)
    srv.start()
    try:
        monkeypatch.setenv('SHION_PORT',str(srv.port))
        record=tmp_path/'inactive.json'
        record.write_text('{}',encoding='utf-8')
        raw=json.dumps({'session_id':'s','rate_limits':{'five_hour':{'used_percentage':42,'resets_at':2000000000}},
                        'transcript_path':'PRIVATE','message':'PRIVATE','cwd':'PRIVATE'}).encode()
        result=subprocess.run([sys.executable,str(Path(sl.__file__)), '--record',str(record)],
                              input=raw,capture_output=True,timeout=5)
        assert result.returncode==0 and result.stdout==b'' and result.stderr==b''
        assert events==[('usage_limits',None,{'session':'s','five_hour':{'used_percentage':42,'resets_at':2000000000}})]
    finally:
        srv.stop()


def test_terminal_hook_signal_cannot_latch_over_numeric_recovery():
    limits=Limits()
    limits.update(sample(99),1000)
    limits.signal('session-a',True,1001)
    assert not limits.down
    limits.update(sample(10),1002)
    assert limits.level==0 and limits.pending[0]==0 and limits.reviving
    limits.acknowledge()
    limits.update({'session':'session-a'},1003)
    limits.signal('session-a',True,1004)
    assert limits.level==0


def test_bash_chain_handles_inline_shell_commands(tmp_path):
    record=tmp_path/'record.json'
    record.write_text(json.dumps({'version':1,'original_raw':json.dumps({'type':'command','command':"printf '%s' 'exact shell output'"})}),encoding='utf-8')
    if hc.statusline_shell()[-1]=='-Command':
        pytest.skip('Bash is unavailable in this isolated environment')
    assert sl.chain(b'private',record)==b'exact shell output'


def test_restart_preserves_terminal_speech_dedup_and_recovers_new_window():
    from shion.state import SaveData
    limits=Limits()
    limits.update(sample(95),1000)
    limits.acknowledge()
    save=SaveData(stamina_announced=limits.records(1000))
    restored=SaveData.from_dict(save.to_dict())
    again=Limits(restored.stamina_announced)
    again.refresh(1001)  # Startup without any quota yet must retain future dedup records.
    again.update(sample(95),1002)
    assert again.level==3 and again.pending is None
    again.update(sample(10),1003)
    assert again.pending[0]==0 and again.reviving
    again.acknowledge()
    again.update(sample(95),1004)
    again.update(sample(10),1005)
    assert again.pending is None
    again.update(sample(95,reset=3000),2001)
    assert again.pending[0]==3
    assert Limits({'nan':[1],'2000':[True,1,5],'invalid':'bad'}).records(0)=={'2000.0':[1]}


def _chain_env(tmp_path, monkeypatch, command):
    data = tmp_path / 'data'
    monkeypatch.setenv('SHION_DATA_DIR', str(data))
    record = tmp_path / 'record.json'
    record.write_text(json.dumps({'version': 1, 'original_raw': json.dumps({'type': 'command', 'command': command})}),
                      encoding='utf-8')
    return data / 'statusline-last.bin', record


def test_statusline_chain_caches_success_and_replays_on_failure(tmp_path, monkeypatch):
    cache, record = _chain_env(tmp_path, monkeypatch, 'echo hello')
    monkeypatch.setattr('tools.hooks_config.statusline_shell', lambda: ['cmd', '/c'])
    out = sl.chain(b'{}', record)
    assert out.strip() == b'hello' and cache.read_bytes() == out
    record.write_text(json.dumps({'version': 1, 'original_raw': json.dumps({'type': 'command', 'command': 'exit 3'})}),
                      encoding='utf-8')
    assert sl.chain(b'{}', record) == out  # failure replays the last good output


def test_statusline_chain_replays_cache_on_timeout_and_empty_without_cache(tmp_path, monkeypatch):
    cache, record = _chain_env(tmp_path, monkeypatch, 'ping -n 6 127.0.0.1 >nul')
    monkeypatch.setattr('tools.hooks_config.statusline_shell', lambda: ['cmd', '/c'])
    assert sl.chain(b'{}', record) == b''
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'cached line')
    assert sl.chain(b'{}', record) == b'cached line'
