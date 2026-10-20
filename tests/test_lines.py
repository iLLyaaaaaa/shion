import json
import random

import pytest

from shion.lines import (
    FALLBACK_LANG, LINES_DIR, Lines, available_languages, resolve_language,
)

# 状态机和界面层会用到的台词类别（见 progress.md 的“第 3 步接口”）
NEEDED = {
    "poke", "stop", "dizzy", "drag", "wake", "neglect_return", "praise_menu",
    "claude_working", "claude_done", "pat", "greeting", "claude_waiting",
    "intro", "startup", "idle_talk",
    "plan_ready", "cheek_pull", "cheek_release", "tickle", "tickle_end",
}


def test_zh_json_has_every_key_the_state_machine_uses():
    assert NEEDED <= Lines().keys()


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_every_language_has_nonempty_introductions(lang):
    raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    assert raw["lines"]["intro"]
    assert Lines(lang).pick("intro") in raw["lines"]["intro"]


def test_pick_never_repeats_consecutively():
    lines = Lines(rng=random.Random(5))
    prev = None
    for _ in range(200):
        cur = lines.pick("poke")
        assert cur != prev
        prev = cur


def test_single_line_category_and_unknown_key():
    lines = Lines()
    assert lines.pick("praise_menu") == lines.pick("praise_menu")  # 只有一句时允许重复
    assert lines.pick("no_such_key") is None


def test_missing_directory_is_not_fatal(tmp_path):
    lines = Lines(directory=tmp_path)
    assert lines.pick("poke") is None
    assert lines.ui("menu_quit") == "menu_quit"  # 找不到就返回 key，不崩


# ---- 真实语言文件 ----
def _raw(code):
    return json.loads((LINES_DIR / f"{code}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", [c for c, _ in available_languages()])
def test_every_shipped_language_is_complete(code):
    zh, raw = _raw("zh"), _raw(code)
    assert NEEDED <= set(raw["lines"])
    assert set(raw["ui"]) == set(zh["ui"])
    assert raw["meta"]["name"] and isinstance(raw["meta"]["font_fallback"], list)
    assert all(isinstance(s, str) and s for pool in raw["lines"].values() for s in pool)


@pytest.mark.parametrize("code", ["zh", "en", "ja"])
def test_ready_reminders_are_native_and_interface_has_no_claude(code):
    raw = _raw(code)
    for key in ("plan_ready", "cheek_pull", "cheek_release", "tickle", "tickle_end", "claude_done"):
        assert raw["lines"][key]  # 必须原生提供，不能依赖中文回退
        assert Lines(code).pick(key) in raw["lines"][key]
    visible = list(raw["ui"].values()) + [s for pool in raw["lines"].values() for s in pool]
    assert all("claude" not in text.casefold() for text in visible)
    assert "done_summary" not in raw["ui"]


def test_shipped_languages_are_zh_en_ja_with_zh_first():
    langs = available_languages()
    assert [c for c, _ in langs] == ["zh", "en", "ja"]
    assert dict(langs)["en"] == "English"


def test_english_expression_and_action_menu_labels():
    lines = Lines("en")
    assert [lines.ui(key) for key in (
        "expression_stop", "expression_neglect2", "menu_auto_expression", "action_face"
    )] == ["Flustered", "Teary", "Auto expressions", "Face the mouse"]


# ---- 切换与回退 ----
def test_set_language_switches_lines_ui_and_fonts():
    lines = Lines()
    zh_poke = set(lines._lines["poke"])
    lines.set_language("en")
    assert lines.lang == "en"
    assert lines.ui("menu_quit") == "Quit"
    assert not zh_poke & set(lines._lines["poke"])
    assert lines.font_fallback == ["Segoe UI"]
    lines.set_language("ja")
    assert lines.font_fallback[0] == "Yu Gothic UI"


def test_unknown_language_falls_back_to_zh():
    lines = Lines("xx")
    assert lines.lang == FALLBACK_LANG
    assert lines.ui("menu_quit") == _raw("zh")["ui"]["menu_quit"]


def _write(d, code, lines=None, ui=None, meta=None):
    (d / f"{code}.json").write_text(
        json.dumps({"meta": {"name": code.upper()} if meta is None else meta, "lines": lines or {}, "ui": ui or {}}),
        encoding="utf-8",
    )


def test_missing_keys_fall_back_to_chinese(tmp_path):
    _write(tmp_path, "zh", {"poke": ["中文戳"], "wake": ["中文醒"]}, {"menu_quit": "退出", "menu_size": "大小"})
    _write(tmp_path, "fr", {"poke": ["Quoi ?"]}, {"menu_quit": "Quitter"})
    lines = Lines("fr", directory=tmp_path)
    assert lines.pick("poke") == "Quoi ?"
    assert lines.pick("wake") == "中文醒"  # fr 没有 → 回退中文
    assert lines.ui("menu_quit") == "Quitter"
    assert lines.ui("menu_size") == "大小"


def test_ui_placeholders_and_bad_format_are_safe(tmp_path):
    _write(tmp_path, "zh", ui={"a": "{x} 和 {y}", "b": "{oops}"})
    lines = Lines(directory=tmp_path)
    assert lines.ui("a", x=1, y=2) == "1 和 2"
    assert lines.ui("b", x=1) == "{oops}"  # 缺占位符不抛异常


def test_empty_pool_in_language_does_not_hide_chinese(tmp_path):
    _write(tmp_path, "zh", {"poke": ["中"]})
    _write(tmp_path, "en", {"poke": []})
    assert Lines("en", directory=tmp_path).pick("poke") == "中"


# ---- 扫描 ----
def test_scan_picks_up_new_language_without_code_changes(tmp_path):
    _write(tmp_path, "zh", meta={"name": "中文"})
    _write(tmp_path, "de", meta={"name": "Deutsch"})
    _write(tmp_path, "ko", meta={})  # 没有 meta.name → 用文件名
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "list.json").write_text("[1,2]", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert available_languages(tmp_path) == [("zh", "中文"), ("de", "Deutsch"), ("ko", "ko")]
    assert Lines(directory=tmp_path).available_languages() == available_languages(tmp_path)
    assert available_languages(tmp_path / "missing") == []


# ---- 跟随系统语言 ----
@pytest.mark.parametrize("locale,expected", [
    ("zh_CN", "zh"), ("zh-TW", "zh"), ("ja_JP", "ja"), ("ja", "ja"),
    ("en_US", "en"), ("fr_FR", "en"), ("de_DE", "en"), ("C", "en"), ("", "en"),
])
def test_first_run_follows_system_locale(locale, expected):
    assert resolve_language(None, locale, ["zh", "en", "ja"]) == expected


def test_saved_language_wins_and_missing_targets_fall_back():
    assert resolve_language("ja", "en_US", ["zh", "en", "ja"]) == "ja"
    assert resolve_language("xx", "ja_JP", ["zh", "en", "ja"]) == "ja"  # 存档语言没了 → 再看系统
    assert resolve_language(None, "ja_JP", ["zh", "en"]) == "zh"  # 目标不存在 → 中文
    assert resolve_language(None, "en_US", ["zh"]) == "zh"
