"""右键菜单分组：顶层项数量/顺序、子菜单内容、勾选与互斥组、tooltip 位置，三语各一遍。"""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from shion.chatgpt import ChatGPTConnection
from tests.test_controller import Env, env, find_action, menu_tree, qapp  # noqa: F401

LANGS = ["zh", "en", "ja"]


def titles(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def sub(menu, key, ctl):
    return find_action(menu, ctl.lines.ui(key)).menu()


def ai_sub(menu, key, ctl):
    """“AI 连接”下的 Claude Code / ChatGPT 子菜单。"""
    return find_action(sub(menu, "menu_ai", ctl), ctl.lines.ui(key)).menu()


def fake_connection(ctl, state, detail=""):
    ctl.connection.inspect = lambda: SimpleNamespace(state=state, detail=detail)


def claude_status(ui, state, activity="idle"):
    return ui("menu_link_status", name=ui("menu_claude"), state=ui("connection_" + state),
              activity=ui("activity_link_" + activity))


def shape(menu):
    return ["-" if a.isSeparator() else a.text() for a in menu.actions()]


def el(menu, text, width):
    """状态行按宽度截断（测试字体比真机宽，短句也可能被截断）。"""
    return menu.fontMetrics().elidedText(text, Qt.ElideRight, width)


ACTIONS = ["link_manage", "link_disable", "link_remove"]


@pytest.mark.parametrize("lang", LANGS)
def test_top_level_is_grouped_into_ten_entries_with_two_separators(env, lang):
    env.ctl.set_language(lang)
    ui = env.ctl.lines.ui
    menu = env.ctl.build_menu()
    shape = ["-" if a.isSeparator() else a.text() for a in menu.actions()]
    status = el(menu, claude_status(ui, "disconnected"), 240)
    assert shape == [ui("menu_talk"), ui("menu_remote"), ui("menu_pet"), ui("menu_mute"), ui("menu_privacy"), "-",
                     status, ui("menu_ai"), ui("menu_settings"), "-", ui("menu_about"), ui("menu_quit")]
    assert len({ui(k) for k in ("menu_talk", "menu_pet", "menu_ai", "menu_settings")}) == 4
    assert all(ui(k) != k for k in ("menu_pet", "menu_ai", "menu_settings"))  # 三语都有，不是回退成 key


@pytest.mark.parametrize("lang", LANGS)
def test_pet_submenu_order_and_nested_groups(env, lang):
    env.ctl.set_language(lang)
    ui = env.ctl.lines.ui
    menu = env.ctl.build_menu()  # 留着引用：顶层菜单被回收时子菜单也会被销毁
    pet = sub(menu, "menu_pet", env.ctl)
    assert [("-" if a.isSeparator() else a.text()) for a in pet.actions()] == [
        ui("menu_expression"), ui("menu_activity"), ui("menu_action"), ui("menu_size"), "-",
        ui("menu_always_on_top"), ui("menu_release_to_taskbar")]
    assert all(a.menu() is not None for a in pet.actions()[:4])


def test_exclusive_groups_keep_exactly_one_checked(env):
    menu = env.ctl.build_menu()
    pet = sub(menu, "menu_pet", env.ctl)
    for key in ("menu_expression", "menu_activity", "menu_size"):
        items = [a for a in sub(menu, key, env.ctl).actions() if a.actionGroup() is not None]
        assert items and items[0].actionGroup().isExclusive()
        assert sum(a.isChecked() for a in items) == 1, key
    langs = find_action(menu, env.ctl.lines.ui("menu_language")).menu().actions()
    assert langs[0].actionGroup().isExclusive() and sum(a.isChecked() for a in langs) == 1
    assert [a.isCheckable() for a in pet.actions() if not a.isSeparator() and a.menu() is None] == [True, True]


def test_toggles_stay_checkable_and_reflect_state(env):
    env.data.bubble_muted = True
    env.data.privacy_mode = True
    env.data.always_on_top = False
    env.data.release_to_taskbar = True
    menu = env.ctl.build_menu()
    ui = env.ctl.lines.ui
    for key, expected in (("menu_mute", True), ("menu_privacy", True), ("menu_always_on_top", False),
                          ("menu_release_to_taskbar", True)):
        act = find_action(menu, ui(key))
        assert act.isCheckable() and act.isChecked() is expected, key
    assert menu.actions()[3].text() == ui("menu_mute") and menu.actions()[4].text() == ui("menu_privacy")


@pytest.mark.parametrize("state,expected", [
    ("disconnected", ACTIONS[:2]),
    ("connected", ACTIONS),  # 已连接也能打开连接面板查看配置
    ("stale", ACTIONS),
    ("error", ACTIONS),
])
@pytest.mark.parametrize("lang", LANGS)
def test_ai_menu_claude_items_follow_connection_state(env, state, expected, lang):
    env.ctl.set_language(lang)
    fake_connection(env.ctl, state)
    ui = env.ctl.lines.ui
    menu = env.ctl.build_menu()
    status = claude_status(ui, state)
    assert titles(sub(menu, "menu_ai", env.ctl)) == [ui("menu_claude")]  # 没启用 ChatGPT：只有 Claude Code
    claude = ai_sub(menu, "menu_claude", env.ctl)
    rows = [ui("menu_link_connection", state=ui("connection_" + state)), ui("menu_link_activity", state=ui("activity_link_idle"))]
    assert shape(claude) == [el(claude, r, 360) for r in rows] + ["-"] + [ui(k) for k in expected]
    items = [a for a in claude.actions() if not a.isSeparator()]
    assert [a.isEnabled() for a in items] == [False, False] + [True] * len(expected)
    assert not any("Claude" in a.text() for a in items)  # 品牌名只在子菜单标题和顶层名称里
    assert titles(menu)[5] == el(menu, status, 240) and status.startswith(ui("menu_claude"))  # 顶层状态行带名字，且是禁用项
    assert menu.actions()[6].toolTip() in (status, menu.actions()[6].text())  # 截断时全文在 tooltip
    assert not menu.actions()[6].isEnabled()


def test_connection_detail_tooltip_stays_on_last_connection_item(env):
    fake_connection(env.ctl, "stale", "路径失效的详细说明")
    menu = env.ctl.build_menu()
    items = [a for a in ai_sub(menu, "menu_claude", env.ctl).actions() if not a.isSeparator()]
    # detail 只挂在“最后添加的连接项”：断开（状态行、开关不抢它）
    assert [a.toolTip() == "路径失效的详细说明" for a in items] == [False] * 4 + [True]
    assert items[4].text() == env.ctl.lines.ui("link_remove")
    assert all(a.toolTip() in ("", a.text()) for a in items[2:4])  # 操作项没有自定义 tooltip
    assert all(a.toolTip() in ("", a.text()) for a in menu.actions() if a.menu() is None and a.isEnabled())
    fake_connection(env.ctl, "disconnected", "还没连接")
    menu = env.ctl.build_menu()
    items = [a for a in ai_sub(menu, "menu_claude", env.ctl).actions() if not a.isSeparator()]
    assert [a.toolTip() == "还没连接" for a in items] == [False, False, True, False]  # 没有断开项：挂在“连接 / 查看配置”


@pytest.mark.parametrize("lang", LANGS)
def test_both_provider_submenus_share_structure_and_labels(env, tmp_path, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    fake_connection(ctl, "connected")
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    menu = ctl.build_menu()
    claude, chat = ai_sub(menu, "menu_claude", ctl), ai_sub(menu, "menu_chatgpt", ctl)
    prefixes = [ui("menu_link_connection", state=""), ui("menu_link_activity", state="")]
    for part in (claude, chat):
        rows = shape(part)
        assert [r.startswith(p) for r, p in zip(rows, prefixes)] == [True, True]
        assert rows[2:] == ["-"] + [ui(k) for k in ACTIONS]
        assert not any(r.startswith("ChatGPT") for r in rows)  # 子菜单状态行不再带前缀
    assert shape(chat)[0] == el(chat, ui("menu_link_connection", state=ui("link_state_not_installed")), 360)


def test_chatgpt_connection_and_activity_states(env, tmp_path, monkeypatch):
    ctl = env.ctl
    ui = ctl.lines.ui
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    from shion import chatgpt as module
    monkeypatch.setattr(module.config, "read_ownership", lambda *a: b"{}")
    assert ctl.chatgpt.connection_state() == "installed"

    def broken(*a):
        raise module.config.Conflict("legacy")
    monkeypatch.setattr(module.config, "read_ownership", broken)
    assert ctl.chatgpt.connection_state() == "error"
    text, hint = ctl.chatgpt.activity(ui)  # 刚启动没有历史快照：待确认，原来的说明放进 tooltip
    assert text == ui("activity_link_unknown", rounds=ui("activity_link_rounds", count=0))
    assert hint == ui("link_unknown_hint") and "ChatGPT" not in hint
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert chat.actions()[1].toolTip().endswith(hint)  # 截断时前面还有整行全文
    ctl.chatgpt._unobserved_start = False
    assert ctl.chatgpt.activity(ui) == (ui("activity_link_rounds", count=0), None)
    ctl.chatgpt.enabled = False
    assert ctl.chatgpt.connection_state() == "off"
    assert ctl.chatgpt.activity(ui) == (ui("activity_link_none"), None)


@pytest.mark.parametrize("paused,pending,working,expected", [
    (True, True, True, "stopped"), (False, True, True, "permission"),
    (False, False, True, "working"), (False, False, False, "idle"),
])
def test_claude_activity_comes_from_state_machine(env, monkeypatch, paused, pending, working, expected):
    ctl = env.ctl
    ctl.state.paused = paused
    monkeypatch.setattr(ctl.hub.permissions, "pending", lambda: [object()] if pending else [])
    monkeypatch.setattr(ctl.state, "is_working", lambda now: working)
    assert ctl.claude_activity() == expected
    ctl.hub.set_link_enabled(False)
    assert ctl.claude_activity() == "off"


def test_top_level_rows_elide_to_240_with_full_tooltip(env, monkeypatch):
    ctl = env.ctl
    long_state = "很长的连接状态 long connection state " * 6
    real = ctl.lines.ui
    monkeypatch.setattr(ctl.lines, "ui", lambda key, **kw: long_state if key == "connection_disconnected" else real(key, **kw))
    menu = ctl.build_menu()
    row = menu.actions()[6]
    full = real("menu_link_status", name=real("menu_claude"), state=long_state, activity=real("activity_link_idle"))
    assert row.text().endswith("…") and menu.fontMetrics().horizontalAdvance(row.text()) <= 240
    assert row.toolTip() == full and not row.isEnabled()


def test_disabled_link_greys_remote_submenu_and_flips_label(env):
    ctl = env.ctl
    ui = ctl.lines.ui
    ctl.toggle_claude_link()
    menu = ctl.build_menu()
    assert not menu.actions()[1].isEnabled() and menu.actions()[1].text() == ui("menu_remote")
    claude = ai_sub(menu, "menu_claude", ctl)
    assert ui("link_enable") in titles(claude) and ui("link_disable") not in titles(claude)
    assert titles(claude)[1] == el(claude, ui("menu_link_activity", state=ui("activity_link_off")), 360)
    ctl.toggle_claude_link()
    menu = ctl.build_menu()
    assert menu.actions()[1].isEnabled()
    assert ui("link_disable") in titles(ai_sub(menu, "menu_claude", ctl))


@pytest.mark.parametrize("lang", LANGS)
def test_chatgpt_status_line_and_submenu_only_when_present(env, tmp_path, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    plain = ctl.build_menu()
    before = titles(plain)
    assert not any("ChatGPT" in t for t in before) and titles(sub(plain, "menu_ai", ctl)) == [ui("menu_claude")]
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    menu = ctl.build_menu()
    top = [a for a in menu.actions() if not a.isSeparator()]
    assert len(top) == len(before) + 1
    chatgpt_line = top[6]
    full = ctl.chatgpt.status(ui)
    assert not chatgpt_line.isEnabled() and full in chatgpt_line.toolTip()  # 原来的多行全文仍在 tooltip
    assert ctl.chatgpt.connection_state() == "not_installed"
    expected = ui("menu_link_status_bare", name=ui("menu_chatgpt"), state=ui("link_state_not_installed"))
    # 未安装：只有“ChatGPT：未安装”，没有活动轮次和“待确认”
    assert chatgpt_line.text() in (expected, menu.fontMetrics().elidedText(expected, Qt.ElideRight, 240))
    assert ui("activity_link_rounds", count=0) not in chatgpt_line.text()
    assert "\n" not in chatgpt_line.text() and menu.fontMetrics().horizontalAdvance(chatgpt_line.text()) <= 240
    assert titles(sub(menu, "menu_ai", ctl)) == [ui("menu_claude"), ui("menu_chatgpt")]  # Claude Code 在前，ChatGPT 在后
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert [a.isEnabled() for a in chat.actions() if not a.isSeparator()] == [False, False, True, True, True]
    assert titles(chat)[1] == el(chat, ui("menu_link_activity", state=ui("activity_link_none")), 360)  # 活动：—
    assert chat.actions()[1].toolTip() in ("", chat.actions()[1].text())  # 没有“待确认”说明


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("code", ["installed", "off", "error"])
def test_chatgpt_status_line_keeps_activity_in_other_states(env, tmp_path, monkeypatch, lang, code):
    """已安装、临时关闭、出错时仍是“名称：状态 · 活动”，子菜单活动行照旧。"""
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    from shion import chatgpt as module

    def ownership(*a):
        if code == "error":
            raise module.config.Conflict("legacy")
        return b"{}"
    monkeypatch.setattr(module.config, "read_ownership", ownership)
    ctl.chatgpt.enabled = code != "off"
    assert ctl.chatgpt.connection_state() == code
    activity, _ = ctl.chatgpt.activity(ui)
    if code == "off":
        assert activity == ui("activity_link_none")
    else:
        assert activity == ui("activity_link_unknown", rounds=ui("activity_link_rounds", count=0))
    menu = ctl.build_menu()
    line = [a for a in menu.actions() if not a.isSeparator()][6]
    expected = ui("menu_link_status", name=ui("menu_chatgpt"), state=ui("link_state_" + code), activity=activity)
    assert line.text() in (expected, menu.fontMetrics().elidedText(expected, Qt.ElideRight, 240))
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert titles(chat)[1] == el(chat, ui("menu_link_activity", state=activity), 360)


@pytest.mark.parametrize("lang", LANGS)
def test_submenu_status_rows_elide_to_360_with_full_tooltip(env, tmp_path, monkeypatch, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    long_text = "很长的活动说明 long activity text " * 12
    monkeypatch.setattr(ctl.chatgpt, "activity", lambda _ui: (long_text, "提示"))
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    row = chat.actions()[1]
    assert row.text().endswith("…") and chat.fontMetrics().horizontalAdvance(row.text()) <= 360
    assert row.toolTip() == ui("menu_link_activity", state=long_text) + "\n提示"


def test_chatgpt_submenu_disabled_shows_off_and_enable(env, tmp_path):
    ctl = env.ctl
    ui = ctl.lines.ui
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ctl.chatgpt.enabled = False
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert shape(chat) == [el(chat, ui("menu_link_connection", state=ui("link_state_off")), 360),
                           el(chat, ui("menu_link_activity", state=ui("activity_link_none")), 360), "-",
                           ui("link_manage"), ui("link_enable"), ui("link_remove")]
    assert menu.actions()[1].isEnabled()  # ChatGPT 关闭不影响 Claude 的工作遥控


@pytest.mark.parametrize("lang", LANGS)
def test_settings_autostart_stale_and_oserror_are_kept(env, monkeypatch, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    monkeypatch.setattr(ctl.startup, "inspect", lambda: "stale")
    menu = ctl.build_menu()
    auto = [a for a in sub(menu, "menu_settings", ctl).actions() if a.menu() is None]
    assert [a.text() for a in auto] == [ui("menu_autostart_stale")] and auto[0].isCheckable() and not auto[0].isChecked()

    def denied():
        raise PermissionError("denied")

    monkeypatch.setattr(ctl.startup, "inspect", denied)
    menu = ctl.build_menu()
    auto = [a for a in sub(menu, "menu_settings", ctl).actions() if a.menu() is None][0]
    assert not auto.isEnabled() and "denied" in auto.toolTip()


def test_menus_holding_tooltips_have_them_enabled(env, tmp_path):
    # QMenu 默认 toolTipsVisible() 为 False：不开启的话连接详情、ChatGPT 状态全文、自启错误都不会显示。
    env.ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    menu = env.ctl.build_menu()
    assert menu.toolTipsVisible()
    assert sub(menu, "menu_ai", env.ctl).toolTipsVisible()
    assert ai_sub(menu, "menu_claude", env.ctl).toolTipsVisible()
    assert ai_sub(menu, "menu_chatgpt", env.ctl).toolTipsVisible()
    assert sub(menu, "menu_settings", env.ctl).toolTipsVisible()


def test_remote_submenu_unchanged_and_second(env):
    menu = env.ctl.build_menu()
    assert menu.actions()[1].menu() is not None
    assert titles(menu.actions()[1].menu()) == ["停下", "立即中断", "做得好", "有问题……"]
    tree = menu_tree(menu)
    assert tree[0] == "互动" and tree[1][0] == "工作遥控"
