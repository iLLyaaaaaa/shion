"""S1: --renderer v3 entry, state → V3 expression mapping and texture scale."""
import numpy as np
import pytest
from PySide6.QtCore import Qt

from shion.pet_window import MARGIN_BOTTOM, PROP_STATES, SEQUENCE_GROUPS, STATES, PetWindow
from shion.v3_display import (STATE_EXPRESSIONS, V2_VISIBLE_RATIO, expression_for,
                              logical_scale, texture_scale)

V3_FACES = {"smug", "neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make(qapp, height=200, dpr=1.0, clock=None):
    from shion.v3_window import V3PetWindow
    t = clock if clock is not None else [100.0]
    w = V3PetWindow(height=height, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=dpr)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    return w, t


def test_every_state_and_sequence_frame_has_a_v3_expression():
    for state in STATES + list(PROP_STATES):
        base = state if state != "blink" else "idle"
        assert expression_for(state, base) in V3_FACES
    for group in SEQUENCE_GROUPS:
        for i in (1, 2, 3):
            assert expression_for(f"{group}_{i}", "idle") in V3_FACES
    with pytest.raises(ValueError):
        expression_for("no_such_frame", "idle")


def test_blink_and_jump_keep_the_base_expression():
    for base in ("idle", "happy", "neglect2", "sleep"):
        assert expression_for("blink", base) == STATE_EXPRESSIONS[base]
        assert expression_for("jump_2", base) == STATE_EXPRESSIONS[base]


def test_texture_follows_display_height_times_dpr():
    for height in (160, 200, 260, 320):
        assert texture_scale(height, 1.5, 1403) == pytest.approx(1.5 * texture_scale(height, 1, 1403))
        assert logical_scale(height, 1403) * 1403 == pytest.approx(height * V2_VISIBLE_RATIO)


@pytest.mark.parametrize("height", (160, 200, 260, 320))
def test_v3_visible_height_matches_v2(qapp, height):
    from v3proto.render import to_pil
    v3, t = make(qapp, height)
    s = v3._v3_settings
    s.breath = s.blink = s.sway = False  # measure the rest pose, not breathing or hair sway
    t[0] += .3
    v3.advance_to(t[0])
    alpha = np.asarray(to_pil(v3.render_frame(1)))[..., 3]
    v2 = PetWindow(height=height, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=1.0)
    v2.set_state("idle", animate=False)

    def extent(window):
        # Downscaling leaves a faint halo; compare the silhouettes as seen.
        a = np.asarray(to_pil(window.render_frame(1)))[..., 3]
        ys = np.nonzero((a > 32).any(1))[0]
        return ys.min(), ys.max()

    top3, bottom3 = extent(v3)
    top2, bottom2 = extent(v2)
    assert v3.height() == v2.height()  # same window height, same floor line
    assert abs(bottom3 - bottom2) <= 2
    assert abs((bottom3 - top3) - (bottom2 - top2)) <= max(2, height * .01)
    v2.close(); v3.close()


def test_dpr_changes_texture_not_logical_size(qapp):
    a, _ = make(qapp, 200, 1.0)
    b, _ = make(qapp, 200, 1.5)
    assert a.size() == b.size()
    assert b.v3_texture_scale == pytest.approx(1.5 * a.v3_texture_scale)
    assert b._v3_image.width() == pytest.approx(1.5 * a._v3_image.width(), abs=2)
    a.close(); b.close()


def test_set_height_keeps_feet_and_set_state_changes_expression(qapp):
    w, t = make(qapp, 200)
    w.move(400, 300)
    feet = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    w.set_height(320)
    assert (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM) == pytest.approx(feet, abs=1)
    assert w.v3_expression == "neutral"
    w.set_state("neglect2", animate=False)
    t[0] += .2
    w.advance_to(t[0])
    assert w.v3_expression == "teary"
    w.close()


def test_snapshot_entry_selects_the_renderer(qapp, tmp_path):
    from shion.app import SnapshotScene, snapshot, window_class
    from shion.v3_window import V3PetWindow
    assert window_class() is PetWindow and window_class("v2") is PetWindow
    assert window_class("v3") is V3PetWindow
    with SnapshotScene("idle", 200) as scene:
        assert type(scene.win) is PetWindow
    out = tmp_path / "v3.png"
    assert snapshot(str(out), "happy", renderer="v3") == 0
    from PIL import Image
    with Image.open(out) as im:
        assert np.asarray(im.convert("RGBA"))[..., 3].any()
