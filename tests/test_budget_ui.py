from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QSystemTrayIcon

from shion.budget_policy import BudgetPolicy
from shion.budget_ui import parse_custom_budget
from shion.lines import Lines
from shion.state import load
from shion.task_chips import ROW, USAGE_ROW
from tests.test_controller import env, qapp  # noqa: F401


SESSION = "session"


def start(env, **meta):
    env.win.show()
    env.ctl.handle_event("prompt", meta={"session": SESSION, "project": "budget-probe", **meta})
    return env.ctl._task_chips


def action(menu, label):
    return next(action for action in menu.actions() if action.text() == label)


def test_working_chip_right_click_routes_only_claude_code_and_saves_choice(env, monkeypatch):
    ctl = env.ctl
    requests = []
    monkeypatch.setattr(ctl, "_show_budget_menu", lambda chip, pos: requests.append(chip))
    chips = start(env)
    ctl.handle_event("chat_event", meta={"event": "working", "client": "demo"})
    QTest.mouseClick(chips, Qt.RightButton, pos=chips._row_rects[1].center())
    assert not requests
    QTest.mouseClick(chips, Qt.RightButton, pos=chips._row_rects[0].center())
    chip, = requests
    assert chip.status == "working"
    assert ctl.build_budget_menu(replace(chip, source="chatgpt")) is None
    assert ctl.build_budget_menu(replace(chip, source="claude_chat")) is None
    menu = ctl.build_budget_menu(chip)
    ui = ctl.lines.ui
    assert menu.actions()[0].text() == ui("budget_menu_used", used="—")
    assert action(menu, ui("budget_unlimited")).isChecked()
    action(menu, ui("budget_tier_50")).trigger()
    assert ctl.budget_policy.usage(SESSION).budget == 50_000_000
    assert action(ctl.build_budget_menu(chip), ui("budget_tier_50")).isChecked()
    env.scheduler.flush()
    assert load(env.path).session_budgets[SESSION].budget == 50_000_000


@pytest.mark.parametrize("text,units,expected", [
    ("0", 10_000, None), ("-3", 10_000, None), ("1e3", 10_000, None), ("NaN", 1_000_000, None),
    ("0.00001", 10_000, None), (" 10.2 ", 1_000_000, 10_200_000), ("0.0001", 10_000, 1),
])
def test_custom_budget_requires_a_positive_integral_token_count(text, units, expected):
    assert parse_custom_budget(text, units) == expected


@pytest.mark.parametrize("lang,entered", [("zh", "500"), ("en", "5"), ("ja", "500")])
def test_custom_menu_warns_then_accepts_below_usage(env, lang, entered):
    ctl = env.ctl
    ctl.lines = Lines(lang)
    chips = start(env)
    assert not ctl.budget_policy.observe(SESSION, 6_300_000, ctl.hub)
    menu = ctl.build_budget_menu(chips.view.all_chips[0])
    ui = ctl.lines.ui
    action(menu, ui("budget_custom") + "…").trigger()
    dialog = ctl._budget_editor
    button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    dialog.setTextValue("0")
    button.click()
    assert dialog.isVisible() and ui("budget_invalid") in dialog.labelText()
    dialog.setTextValue(entered)
    assert ui("budget_next_checkpoint") in dialog.labelText()
    button.click()
    assert ctl._budget_editor is None
    assert ctl.budget_policy.usage(SESSION).budget == 5_000_000
    assert action(ctl.build_budget_menu(chips.view.all_chips[0]), ui("budget_custom") + "…").isChecked()
    assert not ctl.hub.budget_pauses()
    assert ctl.budget_policy.observe(SESSION, 6_300_000, ctl.hub)


def test_warning_once_for_each_budget_and_retained_across_restart(env, caplog):
    ctl = env.ctl
    ctl.lines = Lines("en")
    start(env)
    ctl.set_default_budget(10_000_000)
    for total in (7_999_999, 8_000_000, 8_100_000):
        ctl.budget_policy.observe(SESSION, total, ctl.hub)
        ctl._speech.dismiss()
        ctl._try_budget_warning()
    warnings = [line for line in env.said if "80%" in line]
    assert warnings == ["budget-probe has used 80% of its budget (8M / 10M)."]
    ctl._set_session_budget(SESSION, 20_000_000)
    ctl.budget_policy.observe(SESSION, 16_000_000, ctl.hub)
    ctl._speech.dismiss()
    ctl._try_budget_warning()
    assert env.said[-1] == "budget-probe has used 80% of its budget (16M / 20M)."
    ctl._set_session_budget(SESSION, 10_000_000)
    assert not ctl.budget_policy.warnings()
    env.scheduler.flush()
    restored = BudgetPolicy(sessions=load(env.path).session_budgets, clock=lambda: env.now)
    restored.observe(SESSION, 9_000_000, ctl.hub)
    assert not restored.warnings()
    assert "budget-probe has used" not in caplog.text


def test_stats_off_disables_session_and_default_choices(env):
    ctl = env.ctl
    ctl.lines = Lines("ja")
    chips = start(env)
    ui = ctl.lines.ui
    ctl.set_usage_enabled(False)
    menu = ctl.build_budget_menu(chips.view.all_chips[0])
    assert all(not item.isEnabled() for item in menu.actions() if not item.isSeparator())
    assert action(menu, ui("budget_tier_10")).toolTip() == ui("budget_usage_required")
    pet_menu = ctl.build_menu()
    settings = action(pet_menu, ui("menu_settings")).menu()
    default = action(settings, ui("budget_default"))
    assert not default.isEnabled()
    assert default.toolTip() == ui("budget_usage_required")
    assert all(not item.isEnabled() for item in default.menu().actions())
    note = action(settings, ui("budget_default_note"))
    assert "予算を少し超える場合があります" in note.text()
    ctl.set_usage_enabled(True)
    pet_menu = ctl.build_menu()
    settings = action(pet_menu, ui("menu_settings")).menu()
    default = action(settings, ui("budget_default"))
    action(default.menu(), ui("budget_tier_10")).trigger()
    assert env.data.task_budget_default == 10_000_000
    ctl.budget_policy.observe("new-session", 1, ctl.hub)
    assert ctl.budget_policy.usage("new-session").budget == 10_000_000


def test_two_line_label_and_tooltip_use_latest_usage_and_hide_private_text(env):
    ctl = env.ctl
    ctl.lines = Lines("en")
    ctl.set_default_budget(10_000_000)
    prompt = "A" * 200
    chips = start(env, prompt_head=prompt)
    ctl.handle_event("working", '{"tool":"edit","target":"private-file.py"}', {"session": SESSION})
    for total, level in ((6_300_000, ""), (8_000_000, "near"), (10_200_000, "over")):
        ctl.budget_policy.observe(SESSION, total, ctl.hub)
        ctl.sync()
        chip = chips.view.all_chips[0]
        assert chip.usage_text.endswith(" / 10M") and chip.usage_color == level
        assert chips._row_rects[0].height() == ROW + USAGE_ROW
        assert chips._row_at(QPoint(20, ROW + 2)) == 0
    assert "Task: " + prompt in chip.tooltip
    assert "Working on: " in chip.tooltip and "private-file.py" in chip.tooltip
    assert "Used: 10.2M (budget 10M)" in chip.tooltip
    assert ctl.hub.wait_gate(0, SESSION) == (True, False)
    ctl.handle_event("budget_pause", meta={"session": SESSION})
    assert chips.view.all_chips[0].status == "waiting"
    panel = ctl._checkpoint
    assert panel._title.text() == "Budget reached · budget-probe"
    ctl.set_privacy(True)
    chip = chips.view.all_chips[0]
    assert chip.name == "Session 1"
    assert chip.usage_text == "10.2M / 10M"
    assert all(secret not in chip.tooltip for secret in (prompt, "private-file.py", "budget-probe"))
    assert panel._title.text() == "Budget reached · Session 1"
    ctl._set_session_budget(SESSION, None)
    assert not ctl.hub.budget_pauses()
    chip = chips.view.all_chips[0]
    assert not chip.usage_text and "Used: 10.2M (Unlimited)" in chip.tooltip


def test_tray_unavailable_does_not_create_menu_or_icon(env, monkeypatch, caplog):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    assert env.ctl.create_tray() is None
    assert not env.ctl.findChildren(QSystemTrayIcon)
    assert not caplog.records


def test_show_from_tray_recovers_window_outside_all_screens(env, monkeypatch):
    ctl = env.ctl
    env.win.move(-10000, -10000)
    raised = []
    monkeypatch.setattr(ctl, "_bring_forward", lambda: raised.append(True))
    ctl.show_from_tray()
    assert env.win.isVisible() and raised
    assert env.win._screen_avail().contains(env.win.geometry().center())
