"""同一项目多个会话：工作遥控菜单 / 检查点面板用第一句话摘要区分（只存内存、不落盘、隐私模式不记录）。"""
import json
import logging

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from shion.server import clean_prompt_head, parse_meta
from shion.sessions import LABEL_W, SessionNames, summarize
from tests.test_controller import env, find_action, qapp  # noqa: F401
from tests.test_hook import run_hook
from tests.test_per_session_remote import held_both, join, proc, remote, server, world2  # noqa: F401

SECRET = "帮我把客户合同里的价格改掉"


def ui(key, **kw):
    return {"session_n": "会话 {n}"}[key].format(**kw)


# ---------------------------------------------------------------- 显示规则
def test_single_session_shows_only_the_folder_even_with_a_prompt():
    names = SessionNames()
    names.note("s1", "proj", "修一下菜单")
    names.note("s2", "other", "写文档")
    assert names.labels(["s1", "s2"], False, ui) == {"s1": "proj", "s2": "other"}


def test_two_sessions_in_one_folder_show_their_first_prompt():
    names = SessionNames()
    names.note("s1", "proj", "修一下菜单截断的问题顺便补测试")
    names.note("s2", "proj", "Write README")
    assert names.labels(["s2", "s1"], False, ui) == {
        "s1": "proj · 修一下菜单截断的问题顺便…", "s2": "proj · Write README"}


def test_same_prompt_gets_an_extra_number():
    names = SessionNames()
    for s in ("s1", "s2", "s3"):
        names.note(s, "proj", "继续")
    assert names.labels(["s1", "s2", "s3"], False, ui) == {
        "s1": "proj · 继续", "s2": "proj · 继续 (2)", "s3": "proj · 继续 (3)"}


def test_session_without_a_first_prompt_falls_back_to_numbering():
    names = SessionNames()
    names.note("s1", "proj")  # 诗音启动前就开着的会话：没收到第一句话
    names.note("s2", "proj", "修 bug")
    names.note("s3", "proj")
    assert names.labels(["s1", "s2", "s3"], False, ui) == {
        "s1": "proj", "s2": "proj · 修 bug", "s3": "proj (3)"}


def test_only_the_first_prompt_is_kept():
    names = SessionNames()
    names.note("s1", "proj", "第一句")
    names.note("s1", "proj", "第二句")
    names.note("s2", "proj", "别的")
    assert names.labels(["s1", "s2"], False, ui)["s1"] == "proj · 第一句"


def test_privacy_mode_neither_shows_nor_records_prompts():
    names = SessionNames()
    names.note("s1", "proj", SECRET, private=True)
    names.note("s2", "proj", SECRET, private=True)
    assert names._first == {}
    assert names.labels(["s1", "s2"], True, ui) == {"s1": "会话 1", "s2": "会话 2"}
    assert names.labels(["s1", "s2"], False, ui) == {"s1": "proj", "s2": "proj (2)"}  # 关掉隐私后也没有
    names.note("s3", "proj", "可以记")
    names.forget_prompts()
    assert names._first == {}


def test_summary_cleanup():
    assert summarize("  第一行\n第二行\t\t末尾  ") == "第一行 第二行 末尾"
    assert summarize("一二三四五六七八九十甲乙") == "一二三四五六七八九十甲乙"  # 正好 12 个
    assert summarize("一二三四五六七八九十甲乙丙") == "一二三四五六七八九十甲乙…"
    assert summarize("") == "" and summarize(None) == "" and summarize("   ") == ""


@pytest.mark.parametrize("raw,expected", [
    ("修\n一下\r\n菜单", "修 一下 菜单"),
    ("a\x00b\x1bc", "a b c"),
    ("\u202egnp.exe", "gnp.exe"),  # RTL 覆盖等格式字符
    ("   \n\t ", None),
    ("x" * 40, "x" * 40),
    ("x" * 41, None),
    (123, None),
    (None, None),
])
def test_server_cleans_prompt_head(raw, expected):
    assert clean_prompt_head(raw) == expected


def test_bad_prompt_head_is_ignored_not_rejected():
    assert parse_meta({"session": "s1", "prompt_head": "y" * 500}) == {"session": "s1"}
    assert parse_meta({"session": "s1", "prompt_head": ["x"]}) == {"session": "s1"}
    assert parse_meta({"session": "s1", "prompt_head": "ok"}) == {"session": "s1", "prompt_head": "ok"}


# ---------------------------------------------------------------- hook
def test_hook_prompt_head_is_cleaned_and_short():
    from tests.test_hook import load_hook
    h = load_hook()
    assert h.prompt_head("第一行\n\x07第二行" + "长" * 100) == ("第一行 第二行" + "长" * 100)[:40]
    assert h.prompt_head(None) == "" and h.prompt_head("\n\n") == ""


def test_hook_sends_prompt_head_only_on_prompt(tmp_path, monkeypatch):
    from tests.test_hook import load_hook
    h = load_hook()
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    data = {"session_id": "s1", "cwd": r"D:\w\proj", "prompt": "修一下菜单"}
    monkeypatch.setattr(h, "find_cc_process", lambda: None)
    assert "prompt_head" not in h.session_meta("UserPromptSubmit", data)  # 还没有存档：拿不准是不是隐私模式，不发
    (tmp_path / "state.json").write_text("{坏的", encoding="utf-8")
    assert "prompt_head" not in h.session_meta("UserPromptSubmit", data)  # 存档损坏：同上
    (tmp_path / "state.json").write_text(json.dumps({"privacy_mode": False}), encoding="utf-8")
    assert h.session_meta("UserPromptSubmit", data)["prompt_head"] == "修一下菜单"
    assert "prompt_head" not in h.session_meta("PreToolUse", data)
    (tmp_path / "state.json").write_text(json.dumps({"privacy_mode": True}), encoding="utf-8")
    assert "prompt_head" not in h.session_meta("UserPromptSubmit", data)  # 隐私模式：hook 根本不发


def test_hook_to_server_end_to_end(server, tmp_path):  # noqa: F811
    srv, events, _ = server
    stdin = json.dumps({"session_id": "s9", "cwd": r"D:\work\alpha", "prompt": "第一句\n话"}).encode()
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")  # 正常存档、没开隐私模式
    r = run_hook("UserPromptSubmit", srv.port, tmp_path, stdin=stdin)
    assert r.returncode == 0 and r.stderr == b""
    assert events[0][0] == "prompt" and events[0][2]["prompt_head"] == "第一句 话"


# ---------------------------------------------------------------- 控制器：菜单 / 检查点面板 / 日志
def prompt(env, session, project, text):
    env.ctl.handle_event("prompt", None, {"session": session, "project": project, "prompt_head": text})


def work(env, session, project, pid):
    env.ctl.handle_event("working", json.dumps({"tool": "bash", "target": ""}),
                         {"session": session, "tool_id": "t" + session, "proc": proc(pid), "project": project})


@pytest.fixture
def same(env):  # noqa: F811
    env.world = world2()
    env.ctl.process_view = env.world.view()
    env.ctl.hook_images = ()
    prompt(env, "A", "proj", "修菜单")
    prompt(env, "B", "proj", "写文档")
    work(env, "A", "proj", 100)
    work(env, "B", "proj", 110)
    yield env
    env.ctl.hub.resume()


def items(rem, title):
    return [a for a in find_action(rem, title).menu().actions() if not a.isSeparator()]


def test_menu_shows_prompts_for_same_folder_sessions(same):
    _, rem = remote(same)
    assert [a.text() for a in items(rem, "停下")] == ["proj · 修菜单", "proj · 写文档", "全部"]
    assert find_action(rem, "停下").menu().toolTipsVisible()


def test_menu_privacy_mode_hides_and_forgets_prompts(same):
    same.ctl.set_privacy(True)
    _, rem = remote(same)
    assert [a.text() for a in items(rem, "停下")] == ["会话 1", "会话 2", "全部"]
    prompt(same, "C", "proj", SECRET)
    assert same.ctl.session_names._first == {}
    same.ctl.set_privacy(False)
    _, rem = remote(same)
    assert [a.text() for a in items(rem, "停下")][:2] == ["proj", "proj (2)"]  # 关掉隐私后也不会冒出来
    assert all(SECRET[:4] not in a.text() + a.toolTip() for a in items(rem, "停下"))


def test_long_menu_label_is_elided_with_full_tooltip(env):  # noqa: F811
    env.ctl.process_view = world2().view()
    folder = "很长很长的项目文件夹名字" * 4
    prompt(env, "A", folder, "修菜单")
    prompt(env, "B", folder, "写文档")
    work(env, "A", folder, 100)
    work(env, "B", folder, 110)
    _, rem = remote(env)
    sub = find_action(rem, "停下").menu()
    first = items(rem, "停下")[0]
    assert first.toolTip() == f"{folder} · 修菜单"
    assert first.text() != first.toolTip() and first.text().endswith("…")
    assert sub.fontMetrics().horizontalAdvance(first.text()) <= LABEL_W
    env.ctl.hub.resume()


def test_checkpoint_panel_uses_the_same_labels_and_elides(same):
    (ta, _), (tb, _) = held_both(same)
    panel = same.ctl._checkpoint
    assert [name for _, name in panel.rows] == ["proj · 修菜单", "proj · 写文档"]
    long = "长" * 80
    panel.present([("A", long), ("B", "短")], panel._texts)
    labels = [w for w in panel.findChildren(QLabel) if w.toolTip() == long]
    assert labels and labels[0].text().endswith("…")
    assert panel.fontMetrics().horizontalAdvance(labels[0].text()) <= LABEL_W
    same.ctl.resume_work()
    join([ta, tb])


def test_prompt_text_never_reaches_the_log(env, caplog, tmp_path):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    prompt(env, "A", "proj", SECRET)
    prompt(env, "B", "proj", SECRET)
    env.ctl.build_menu()
    env.scheduler.mark_dirty(env.now)
    env.scheduler.flush(env.now)  # 强制写一次存档，确认存档里没有提示词
    assert env.path.exists()
    assert SECRET[:6] not in caplog.text
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET[:6] not in path.read_text(encoding="utf-8", errors="ignore")  # 存档等文件里也没有


def test_server_does_not_log_prompt_head(server, caplog, tmp_path):  # noqa: F811
    srv, events, _ = server
    caplog.set_level(logging.DEBUG)
    stdin = json.dumps({"session_id": "s1", "cwd": r"D:\w\proj", "prompt": SECRET}).encode()
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    run_hook("UserPromptSubmit", srv.port, tmp_path, stdin=stdin)
    assert events and events[0][2]["prompt_head"] == SECRET
    assert SECRET[:6] not in caplog.text
