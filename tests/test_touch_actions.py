"""真实 Qt 手势、时间边界和三语仲裁；不依赖用户鼠标或真实等待。"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from shion.pet_window import MARGIN_TOP, MARGIN_X
from shion.speech import Priority
from tests.test_controller import env, qapp
from tests.test_feedback_ui import move_global


def point(w, x=.5, y=.48):
    sw, sh = w.sprite_size
    return QPoint(MARGIN_X + round(sw * x), MARGIN_TOP + round(sh * y))


def press(w, y=.48):
    pos = point(w, y=y)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, pos)
    return w.mapToGlobal(pos)


def release(w, global_pos):
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(global_pos))


@pytest.mark.parametrize("muted", [True, False])
@pytest.mark.parametrize("key", ["cheek_pull", "cheek_release", "tickle", "tickle_end"])
def test_gesture_dialogue_respects_mute_and_high_priority_work_reminder(env, muted, key):
    env.ctl.set_muted(muted)
    env.ctl.say("Important", priority=Priority.HIGH, category="plan_ready")
    before = list(env.said)
    env.win.gesture.emit(key)
    assert env.said == before


def test_snapshot_cli_rejects_removed_face_flag(qapp, tmp_path):
    from shion.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(["--snapshot", str(tmp_path / "x.png"), "--face", "left"])
    assert exc.value.code == 2


@pytest.mark.parametrize("old", ["face", "turn"])
def test_old_face_and_turn_names_are_ignored(env, monkeypatch, old):
    # V2 版本里同名测试还检查 turn 帧没被载入；V3 没有精灵文件，只保留控制器对旧名字的容错。
    w = env.win
    assert not hasattr(w, "face") and not hasattr(w, "turn")
    env.ctl.do_action(old)  # 旧名字：什么也不做，不报错
    assert not w.motion_active
    monkeypatch.setattr(env.ctl._idle, "step", lambda *args: old)
    env.ctl.tick()  # 旧的待机动作名同样被忽略
    assert not w.motion_active


def test_press_interrupts_jump_and_work_interrupts_only_automatic_jump(env):
    env.win.jump(automatic=True)
    env.ctl.handle_event("working")
    assert not env.win.motion_active
    env.win.jump(automatic=False)
    env.ctl.sync()
    assert env.win.motion_active
    gp = press(env.win, .9)
    assert not env.win.motion_active
    release(env.win, gp)


def test_fixed_expression_restores_after_a_cheek_pinch_without_affection_or_feedback(env):
    env.ctl.select_expression("proud")
    env.ctl.fix_expression(True)
    gp = press(env.win)
    move_global(env.win, gp + QPoint(20, 0))
    release(env.win, gp + QPoint(20, 0))
    env.advance(2)
    assert env.win.displayed_sprite == "proud"
    assert env.data.fixed_expression == "proud"
    assert env.data.affection == env.data.stats["pats"] == 0
    assert env.data.feedback_queue == []
