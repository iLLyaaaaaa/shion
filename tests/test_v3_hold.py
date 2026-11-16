"""S8：working 抱电脑——arms_hold 整块代替两条手臂。"""
import numpy as np
import pytest
from PIL import Image

from shion.v3_display import STATE_ARMS, arms_for, draw_key
from tests.test_v3_display import make, qapp  # noqa: F401  (qapp 是 fixture)
from tests.test_v3_state_pose import run
from v3proto.animation import Animator, Pose, Settings
from v3proto.lift_scenarios import lift_scenario
from v3proto.render import HOLD, Renderer, Rig, to_pil
from v3proto.tickle import in_belly


@pytest.fixture(scope="module")
def rig():
    return Rig()


@pytest.fixture(scope="module")
def renderer(rig, qapp):  # noqa: F811
    return Renderer(rig, .4)


def canvas(rig, **kwargs):
    return np.asarray(rig.rest("neutral", **kwargs))


def test_active_picks_hold_or_arms(rig):
    default = rig.active("neutral")
    hold = rig.active("neutral", arms=HOLD)
    assert "arms_hold" not in default and {"arm_l", "arm_r"} <= set(default)
    assert "arms_hold" in hold and not {"arm_l", "arm_r"} & set(hold)
    assert [n for n in default if n not in ("arm_l", "arm_r")] == [n for n in hold if n != "arms_hold"]
    # 其余代码路径（头部合成、镜像）看到的永远是默认部件表
    assert "arms_hold" not in rig.active("smug")


def test_block_sits_on_the_arm_layer_and_follows_the_body(rig):
    part = rig.parts["arms_hold"]
    assert part["layer"] == rig.parts["arm_l"]["layer"] and part["parent"] == "body"
    assert "pivot" not in part
    x, y, (w, h) = part["x"], part["y"], part["size"]
    assert x >= 0 and y >= 0 and x + w <= rig.size[0] and y + h <= rig.size[1]
    assert rig.images["arms_hold"].size == (w, h)


def test_rest_frame_replaces_the_arms_with_the_block(rig):
    default, hold = canvas(rig), canvas(rig, arms=HOLD)
    # 笔记本电脑盖板中间是不透明的块，和默认帧不同
    cx, cy = 680, 800
    assert hold[cy, cx, 3] == 255 and not np.array_equal(hold[cy, cx], default[cy, cx])

    def layer(name):
        part, image = rig.parts[name], np.asarray(rig.images[name])
        full = np.zeros(rig.size[::-1], bool)
        full[part["y"]:part["y"] + image.shape[0], part["x"]:part["x"] + image.shape[1]] = image[..., 3] > 8
        return full

    # 旧手臂伸出在身体、电脑块之外的部分（两只手尖）在 hold 里不再有任何像素
    others = layer("arms_hold") | layer("body") | layer("body_under")
    left_over = np.zeros(rig.size[::-1], bool)
    for name in ("arm_l", "arm_r"):
        left_over |= layer(name)
    left_over &= ~others
    for name in rig.active("neutral", arms=HOLD):
        if name not in ("arms_hold", "body", "body_under"):
            left_over &= ~layer(name)
    assert left_over.sum() > 2000                       # 手尖确实伸出去了
    assert (hold[..., 3][left_over] <= 8).all()          # 只剩别的部件抗锯齿的淡尾巴
    # 变化只发生在手臂、电脑一带
    ys, xs = np.nonzero((hold != default).any(-1))
    assert xs.min() >= 150 and ys.min() >= 600 and ys.max() <= 1120


def test_hold_never_moves_the_arms(renderer):
    """捏脸挣扎、挠痒躲闪、拎起抬手都带 arm_degrees；抱着电脑时一概不动。"""
    quiet = dict(breath=False, blink=False, sway=False, pinch_maximum=200)
    s = Settings(expression="neutral", arms=HOLD, **quiet)
    for kwargs in (dict(head_y=-1), dict(head_y=-1, pinch_delta=(-80., -6.)), dict(body_scale=1.01, head_y=3)):
        a = to_pil(renderer.render(s, Pose(**kwargs)))
        b = to_pil(renderer.render(s, Pose(arm_degrees=12., **kwargs)))
        assert np.array_equal(np.asarray(a), np.asarray(b)), kwargs
    # 默认手臂确实会随 arm_degrees 动（对照）
    d = Settings(expression="neutral", **quiet)
    a = to_pil(renderer.render(d, Pose(head_y=-1)))
    b = to_pil(renderer.render(d, Pose(head_y=-1, arm_degrees=12.)))
    assert not np.array_equal(np.asarray(a), np.asarray(b))


def test_lift_pose_arm_is_ignored_when_holding(renderer):
    quiet = dict(breath=False, blink=False, sway=False)
    animator = Animator(Settings(expression="neutral", **quiet), 3, star_seed=3)
    pose = lift_scenario(animator, "held", .8)
    assert pose.arm_degrees != 0
    s = Settings(expression="neutral", arms=HOLD, **quiet)
    from dataclasses import replace
    a = to_pil(renderer.render(s, pose))
    b = to_pil(renderer.render(s, replace(pose, arm_degrees=0.)))
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_rest_cache_separates_the_two_arm_styles(renderer):
    quiet = dict(breath=False, blink=False, sway=False)
    default = to_pil(renderer.render(Settings(expression="neutral", **quiet), Pose()))
    hold = to_pil(renderer.render(Settings(expression="neutral", arms=HOLD, **quiet), Pose()))
    again = to_pil(renderer.render(Settings(expression="neutral", **quiet), Pose()))
    assert not np.array_equal(np.asarray(default), np.asarray(hold))
    assert np.array_equal(np.asarray(default), np.asarray(again))


def test_hit_test_counts_the_block_as_body_and_blocks_the_belly(renderer):
    s = Settings(expression="neutral", arms=HOLD)
    d = Settings(expression="neutral")
    pose = Pose(head_y=-1)
    covered = exposed = 0
    for y in range(640, 1100, 8):
        for x in range(250, 900, 8):
            if not in_belly((x, y)):
                continue
            kind_default, _ = renderer.hit_test((x, y), d, pose, crown=True, belly=True)
            kind, _ = renderer.hit_test((x, y), s, pose, crown=True, belly=True)
            part = renderer.rig.parts["arms_hold"]
            alpha = np.asarray(renderer.rig.images["arms_hold"])
            lx, ly = x - part["x"], y - part["y"]
            under_block = 0 <= lx < alpha.shape[1] and 0 <= ly < alpha.shape[0] and alpha[ly, lx, 3] > 64
            if under_block:
                covered += 1
                assert kind == "body", (x, y, kind)          # 可戳，不触发挠痒
            elif kind_default == "belly":
                exposed += 1
                assert kind == "belly", (x, y, kind)        # 电脑以外露出的肚子照旧
    assert covered > 100 and exposed > 20


def test_draw_key_and_state_map_know_about_the_arms():
    pose = Pose()
    assert draw_key("neutral", pose, .4, ()) != draw_key("neutral", pose, .4, (), "hold")
    assert draw_key("neutral", pose, .4, ()) == draw_key("neutral", pose, .4, (), "default")
    assert STATE_ARMS == {"working": "hold"}
    assert arms_for("working") == "hold"
    for state in ("idle", "stop", "sleep", "happy", "slump", "collapse", "desk"):
        assert arms_for(state) == "default"


def test_window_holds_the_laptop_only_while_working(qapp):  # noqa: F811
    w, t = make(qapp, 200, 1.5)
    w.set_state("idle", animate=False)
    run(w, t, .3)
    assert w._v3_settings.arms == "default"
    idle_key = w._v3_key
    w.set_state("working", animate=False)
    run(w, t, .3)
    assert w._v3_settings.arms == "hold"
    assert w._v3_mask_state == "working" and not w.mask().isEmpty()   # 遮罩按新画面重建
    assert w._v3_key != idle_key
    w.set_state("stop", animate=False)
    run(w, t, .3)
    assert w._v3_settings.arms == "default"
    w.set_state("working", animate=False)
    run(w, t, .3)
    assert w._v3_settings.arms == "hold"
    w.close()
