"""Shared token formatting, choices and custom budget input."""
from __future__ import annotations

import re
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QLineEdit

from shion.budget_policy import BUDGET_TIERS


def parse_custom_budget(text: str, units: int) -> int | None:
    text = text.strip()
    if not re.fullmatch(r"[0-9]{1,18}(?:\.[0-9]{1,6})?", text):
        return None
    tokens = Decimal(text) * units
    return int(tokens) if tokens > 0 and tokens == tokens.to_integral_value() else None


def add_budget_choices(menu, ui, current, select, custom, *, tiers=BUDGET_TIERS,
                       unlimited_first=False, disabled_hint=""):
    presets = [(v, ui(f"budget_tier_{v // 1_000_000}")) for v in tiers]
    unlimited = (None, ui("budget_unlimited"))
    items = [*presets, ("custom", ui("budget_custom") + "…")]
    items.insert(0 if unlimited_first else len(items), unlimited)
    menu.setToolTipsVisible(True)
    for value, label in items:
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(current not in (*tiers, None) if value == "custom" else value == current)
        if disabled_hint:
            action.setToolTip(disabled_hint)
            action.setEnabled(False)
        elif value == "custom":
            action.triggered.connect(lambda _=False: custom())
        else:
            action.triggered.connect(lambda _=False, v=value: select(v))


class BudgetInput(QInputDialog):
    def __init__(self, parent, texts, current, apply, *, check=None, warning=None):
        super().__init__(parent)
        self._texts = texts
        self._units = 1_000_000 if texts["lang"] == "en" else 10_000
        self._apply = apply
        self._check = check
        self._warning = warning
        self.setWindowTitle(texts["custom"])
        self.setLabelText(texts["input"])
        self.setOkButtonText(texts["apply"])
        self.setCancelButtonText(texts["cancel"])
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(parent.windowFlags() & Qt.WindowStaysOnTopHint))
        self.setTextValue("" if current is None else format(Decimal(current) / self._units, "f"))
        self._edit = self.findChild(QLineEdit)
        self._edit.setMaxLength(25)
        self._edit.selectAll()
        self.textValueChanged.connect(self._show_warning)
        self._show_warning(self.textValue())

    def _show_warning(self, text):
        value = parse_custom_budget(text, self._units)
        warning = self._warning(value) if value is not None and self._warning else None
        self.setLabelText(self._texts["input"] + ("\n" + warning if warning else ""))

    def accept(self):
        value = parse_custom_budget(self.textValue(), self._units)
        error = self._texts["invalid"] if value is None else self._check(value) if self._check else None
        if error:
            self.setLabelText(error)
            self._edit.selectAll()
            return
        if self._warning:
            warning = self._warning(value)
            if warning and not self.labelText().endswith(warning):
                self.setLabelText(self._texts["input"] + "\n" + warning)
                return
        super().accept()
        self._apply(value)
