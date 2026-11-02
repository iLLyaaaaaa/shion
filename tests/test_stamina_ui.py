"""Synthetic Qt integration: stamina cannot change Claude controls."""
from datetime import timedelta
import pytest
from tests.test_controller import env, qapp
from tests.test_stamina import sample


def update(e, value=96, **kwargs):
    data=sample(value,reset=e.now.timestamp()+3600,**kwargs)
    e.ctl.handle_event('usage_limits',None,data)


def test_terminal_stamina_and_status_only_show_live_numbers(env):
    e=env
    update(e,96)
    assert e.win.sprite_name=='sleep'
    assert '5 小时额度 96%' in e.ctl.status_text()
    assert e.data.stats['claude_tasks']==0
    assert e.data.weekly_stats[str(e.now.date())]['seven_day_peak']==73
    e.ctl.handle_event('usage_limits',None,{'session':'session-a'})
    assert '5 小时额度' not in e.ctl.status_text() and e.win.sprite_name=='idle'


def test_quota_down_does_not_settle_authorization_and_stands_for_panel(env):
    e=env
    rid=e.ctl.hub.permissions.open('Bash','synthetic',session='desktop')
    e.ctl.handle_event('quota_down',None,{'session':'desktop'})
    assert e.ctl.hub.permissions.pending()[0].id==rid
    e.ctl._sync_permission()
    e.ctl.sync()
    assert e.ctl._perm_panel.isVisible() and e.win.sprite_name=='idle'
    e.ctl._on_permission_decided(rid,True)
    e.ctl.sync()
    assert e.win.sprite_name=='sleep'
    assert e.data.weekly_stats[str(e.now.date())]['approvals']==1
    assert '额度' not in e.ctl.status_text()


@pytest.mark.parametrize('protection', ['drag','fixed','manual','eating','paused','working'])
def test_stamina_yields_to_every_protected_state(env,protection):
    e=env
    if protection=='drag': e.state._dragging=True
    elif protection=='fixed': e.data.fixed_expression='proud'
    elif protection=='manual': e.state._manual=('dizzy',e.now+timedelta(seconds=30))
    elif protection=='eating': e.state._eating_until=e.now+timedelta(seconds=30)
    elif protection=='paused': e.state.paused=True
    elif protection=='working': e.state.claude_event('prompt',None,e.now,'work')
    before=e.state.current(e.now)
    update(e)
    assert e.state.current(e.now)==before
    e.ctl._try_stamina_notice(e.now)
    assert e.ctl.limits.pending is not None
    assert not any('撑不住' in s for s in e.said)


def test_revive_only_after_last_session_and_idle_speech_gate(env,monkeypatch):
    e=env
    jumps=[]
    monkeypatch.setattr(e.win,'jump',lambda *a,**k:jumps.append(True))
    for sid in ('a','b'):
        e.ctl.handle_event('quota_down',None,{'session':sid})
    e.ctl._try_stamina_notice(e.now)
    assert e.said[-1]=='今天……撑不住了……'
    e.ctl.handle_event('quota_revive',None,{'session':'a'})
    e.ctl._try_stamina_notice(e.now)
    assert not jumps and e.win.sprite_name=='sleep'
    e.ctl.handle_event('quota_revive',None,{'session':'b'})
    e.mono[0]+=30
    e.ctl._try_stamina_notice(e.now)
    assert jumps==[True] and '满血复活' in e.said[-1]
    e.ctl._try_stamina_notice(e.now)
    assert jumps==[True]


def test_ordinary_stop_and_prompt_never_revive_desktop(env):
    e=env
    e.ctl.handle_event('quota_down',None,{'session':'a'})
    e.ctl.handle_event('prompt',None,{'session':'a'})
    e.ctl.handle_event('stop',None,{'session':'a'})
    assert e.ctl.limits.down=={'a'}
    e.ctl.toggle_claude_link()
    assert not e.ctl.limits.down and e.state.stamina_level==0


def test_quota_row_hidden_when_absent_and_rendered_in_each_language(qapp,monkeypatch):
    from PySide6.QtGui import QPainter
    from shion.weekly import preview
    from shion.weekly_ui import render_card
    from shion.lines import Lines
    draws=[]
    original=QPainter.drawText
    def capture(p,*args):
        draws.append(args[-1])
        return original(p,*args)
    monkeypatch.setattr(QPainter,'drawText',capture)
    for lang in ('zh','en','ja'):
        data=preview(lang)
        label=Lines(lang).ui('weekly_quota',value='93')
        render_card(data)
        assert label not in draws
        data['totals']['seven_day_peak']=93
        render_card(data)
        assert label in draws
        draws.clear()


def test_weekly_does_not_rebook_another_sessions_old_seven_day_value(env):
    e=env
    update(e,42)
    e.now+=timedelta(days=1)
    e.ctl.handle_event('usage_limits',None,sample(42,reset=e.now.timestamp()+100,sid='other',seven=None))
    assert 'seven_day_peak' not in e.data.weekly_stats.get(str(e.now.date()),{})


def test_initial_spirit_speaks_once_without_revival_jump(env,monkeypatch):
    e=env
    jumps=[]
    monkeypatch.setattr(e.win,'jump',lambda **kwargs:jumps.append(True))
    update(e,10)
    e.ctl._try_stamina_notice(e.now)
    assert e.said[-1]==e.ctl.lines.ui('stamina_ready') and not jumps
    e.mono[0]+=30
    update(e,10)
    e.ctl._try_stamina_notice(e.now)
    assert len(e.said)==1


def test_repeated_quota_updates_do_not_defer_save_or_redraw_weekly(env,monkeypatch):
    from types import SimpleNamespace
    e=env
    dirty,draws=[],[]
    monkeypatch.setattr(e.scheduler,'mark_dirty',dirty.append)
    e.ctl._weekly_window=SimpleNamespace(isVisible=lambda:True,update_report=draws.append)
    try:
        update(e,42,seven=73)
        update(e,42,seven=73)
        update(e,42,seven=70)
        assert len(dirty)==len(draws)==1
        update(e,42,seven=74)
        assert len(dirty)==len(draws)==2
    finally:
        e.ctl._weekly_window=None
