"""右键菜单分组：顶层项数量/顺序、子菜单内容、勾选与互斥组、tooltip 位置，三语各一遍。"""
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize("lang", LANGS)
def test_top_level_is_grouped_into_ten_entries_with_two_separators(env, lang):
    env.ctl.set_language(lang)
    ui = env.ctl.lines.ui
    menu = env.ctl.build_menu()
    shape = ["-" if a.isSeparator() else a.text() for a in menu.actions()]
    status = ui("menu_connection_status", state=ui("connection_disconnected"))
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
    ("disconnected", ["menu_connect"]),
    ("connected", ["menu_disconnect"]),
    ("stale", ["menu_reconnect", "menu_disconnect"]),
    ("error", ["menu_connect", "menu_disconnect"]),
])
@pytest.mark.parametrize("lang", LANGS)
def test_ai_menu_claude_items_follow_connection_state(env, state, expected, lang):
    env.ctl.set_language(lang)
    fake_connection(env.ctl, state)
    ui = env.ctl.lines.ui
    menu = env.ctl.build_menu()
    status = ui("menu_connection_status", state=ui("connection_" + state))
    assert titles(sub(menu, "menu_ai", env.ctl)) == [ui("menu_claude")]  # 没启用 ChatGPT：只有 Claude Code
    claude = ai_sub(menu, "menu_claude", env.ctl)
    assert titles(claude) == [status] + [ui(k) for k in expected]  # 第一行是禁用的状态行，后面才是连接类项
    assert not claude.actions()[0].isEnabled() and all(a.isEnabled() for a in claude.actions()[1:])
    assert titles(menu)[5] == status and "Claude Code" in status  # 顶层状态行带名字，且是禁用项
    assert not menu.actions()[6].isEnabled()


def test_connection_detail_tooltip_stays_on_last_connection_item(env):
    fake_connection(env.ctl, "stale", "路径失效的详细说明")
    menu = env.ctl.build_menu()
    items = ai_sub(menu, "menu_claude", env.ctl).actions()
    # 没设置 tooltip 的动作，Qt 返回的是它自己的文本；detail 只挂在原来“最后添加的那项”：断开（状态行不抢它）
    assert [a.toolTip() for a in items] == [items[0].text(), items[1].text(), "路径失效的详细说明"]
    assert items[2].text() == env.ctl.lines.ui("menu_disconnect")
    assert all(a.toolTip() in ("", a.text()) for a in menu.actions() if a.menu() is None)
    fake_connection(env.ctl, "disconnected", "还没连接")
    menu = env.ctl.build_menu()
    items = ai_sub(menu, "menu_claude", env.ctl).actions()
    assert [a.toolTip() for a in items] == [items[0].text(), "还没连接"]


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
    assert not chatgpt_line.isEnabled() and chatgpt_line.toolTip() == full  # 顶层只放截断的一行，全文在 tooltip
    assert chatgpt_line.text().startswith("ChatGPT") and "\n" not in chatgpt_line.text()
    assert menu.fontMetrics().horizontalAdvance(chatgpt_line.text()) <= 240
    assert titles(sub(menu, "menu_ai", ctl)) == [ui("menu_claude"), ui("menu_chatgpt")]  # Claude Code 在前，ChatGPT 在后
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    rows = len(full.split("\n"))
    assert [a.isEnabled() for a in chat.actions()] == [False] * rows + [True, True, True]


@pytest.mark.parametrize("lang", LANGS)
def test_chatgpt_submenu_shows_status_one_line_per_item_and_elides_long_ones(env, tmp_path, monkeypatch, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    real = ctl.chatgpt.status(ui)
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert chat.toolTipsVisible()
    status_rows = chat.actions()[:-3]
    assert [a.isEnabled() for a in status_rows] == [False] * len(real.split("\n"))
    assert len(status_rows) >= 2  # 启用时：计数行 + 状态行
    assert all("\n" not in a.text() for a in chat.actions())
    for row, line in zip(status_rows, real.split("\n")):
        assert chat.fontMetrics().horizontalAdvance(row.text()) <= 360
        assert row.toolTip() == line  # 截断的行 tooltip 是全文；没截断的 Qt 默认回退为文本，也等于这一行

    long_line = "ChatGPT " + "很长的状态说明 long status text " * 12
    monkeypatch.setattr(ctl.chatgpt, "status", lambda _ui: "短行\n" + long_line + "\n第三行")
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    short, long_row, third = chat.actions()[:3]
    assert len(chat.actions()) == 3 + 3 and not any(a.isEnabled() for a in (short, long_row, third))
    assert short.text() == "短行" and third.text() == "第三行"
    assert short.toolTip() == short.text() and third.toolTip() == third.text()  # 未截断：不设自定义 tooltip（Qt 默认回退为文本）
    assert long_row.text().endswith("…") and long_row.text() != long_line
    assert chat.fontMetrics().horizontalAdvance(long_row.text()) <= 360
    assert long_row.toolTip() == long_line


def test_chatgpt_submenu_disabled_status_is_a_single_row(env, tmp_path):
    ctl = env.ctl
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ctl.chatgpt.enabled = False
    menu = ctl.build_menu()
    chat = ai_sub(menu, "menu_chatgpt", ctl)
    assert [a.isEnabled() for a in chat.actions()] == [False, True, True, True]
    assert chat.actions()[0].text() == ctl.lines.ui("chatgpt_disabled")


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
