import math
import pytest
from video_harness.blender_renderer import callout_math as cm


def test_hud_scale_matches_direction_reference():
    assert cm.hud_scale('ORTHO', 16.0, 36.0, 50.0) == pytest.approx(1.0)
    assert cm.hud_scale('ORTHO', 24.0, 36.0, 50.0) == pytest.approx(1.5)
    # Perspective: visible width at HUD depth 2 is 2*sensor/lens.
    assert cm.hud_scale('PERSP', 0, 36.0, 4.5) == pytest.approx(1.0)


def test_project_ortho_and_persp_and_behind_camera():
    assert cm.project_to_ndc([4, 0, -5], 'ORTHO', 16, 36, 50, 16 / 9) == pytest.approx((0.5, 0.0))
    assert cm.project_to_ndc([0, 2.25, -5], 'ORTHO', 16, 36, 50, 16 / 9) == pytest.approx((0.0, 0.5))
    nx, ny = cm.project_to_ndc([1.8, 0, -5], 'PERSP', 0, 36, 50, 16 / 9)
    assert nx == pytest.approx(1.0) and ny == pytest.approx(0.0)
    with pytest.raises(ValueError, match='behind'):
        cm.project_to_ndc([0, 0, 1], 'PERSP', 0, 36, 50, 16 / 9)


def test_ndc_to_unit_flips_y():
    assert cm.ndc_to_unit(-1, 1) == (0.0, 0.0)
    assert cm.ndc_to_unit(1, -1) == (1.0, 1.0)


def test_text_box_uses_1080p_heights_and_per_script_glyph_widths():
    w, h = cm.text_box('흑운모', 'word', 1920, 1080)
    assert h == pytest.approx(210 / 1080)
    assert w == pytest.approx(1.0 * 210 * 3 / 1920)          # Hangul advances a full em
    w2, h2 = cm.text_box('km', 'unit', 384, 216)
    assert h2 == pytest.approx(105 / 1080)                   # same fraction of the frame at any resolution
    assert w2 == pytest.approx(0.6 * 105 * 2 / 1920)         # Latin about 0.6 em
    w3, _ = cm.text_box('SiO₄ 결합', 'formula', 1920, 1080)
    assert w3 == pytest.approx((0.6 * 5 + 1.0 * 2) * 210 / 1920)


def test_label_rect_sits_outside_anchor_on_requested_side_and_stays_in_safe_area():
    box = (0.2, 0.1)
    right = cm.label_rect((0.5, 0.5), (0.05, 0.08), 'right', box)
    assert right[0] == pytest.approx(0.5 + 0.05 + 0.03) and right[1] == pytest.approx(0.45)
    top = cm.label_rect((0.5, 0.5), (0.05, 0.08), 'top', box)
    assert top[3] == pytest.approx(0.5 - 0.08 - 0.03) and top[0] == pytest.approx(0.4)
    edge = cm.label_rect((0.98, 0.5), (0.01, 0.01), 'right', box)
    assert edge[2] <= 1 - cm.SAFE_MARGIN and edge[0] >= cm.SAFE_MARGIN


def test_leader_points_start_on_anchor_edge_and_end_on_rect_edge():
    rect = cm.label_rect((0.5, 0.5), (0.05, 0.08), 'right', (0.2, 0.1))
    start, elbow, end = cm.leader_points((0.5, 0.5), (0.05, 0.08), rect, 'right')
    assert start == pytest.approx((0.55, 0.5))
    assert end == pytest.approx((rect[0], 0.5))
    assert elbow == pytest.approx((rect[0], 0.5))
    rect_top = cm.label_rect((0.5, 0.5), (0.05, 0.08), 'top', (0.2, 0.1))
    start, elbow, end = cm.leader_points((0.5, 0.5), (0.05, 0.08), rect_top, 'top')
    assert start == pytest.approx((0.5, 0.42)) and end == pytest.approx((0.5, rect_top[3]))


def test_rect_predicates():
    assert cm.rects_overlap([0, 0, .5, .5], [.4, .4, .9, .9])
    assert not cm.rects_overlap([0, 0, .5, .5], [.5, .5, .9, .9])
    assert cm.rect_clipped([0.01, .2, .3, .4])
    assert not cm.rect_clipped([.1, .2, .3, .4])
    assert cm.point_in_rect((.2, .3), [.1, .2, .3, .4])


def test_fade_amount_ramps_in_and_out_over_0_4_seconds():
    assert cm.fade_amount(0, 0, 100, 30) == 0
    assert cm.fade_amount(12, 0, 100, 30) == pytest.approx(1.0)
    assert cm.fade_amount(6, 0, 100, 30) == pytest.approx(0.5)
    assert cm.fade_amount(94, 0, 100, 30) == pytest.approx(0.5)
    assert cm.fade_amount(100, 0, 100, 30) == 0
    assert cm.fade_amount(150, 0, 100, 30) == 0


def test_rotate_inverse_matches_identity_and_quarter_turn():
    assert cm.rotate_inverse([1, 0, 0, 0], [1, 2, 3]) == pytest.approx([1, 2, 3])
    q = [math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)]   # 90° about z
    assert cm.rotate_inverse(q, [1, 0, 0]) == pytest.approx([0, -1, 0], abs=1e-9)


def test_select_sample_frames_defaults_to_full_range_and_dedups():
    assert cm.select_sample_frames({'frame_count': 3}) == [0, 1, 2]
    assert cm.select_sample_frames({'frame_count': 10, 'sample_frames': [5, 2, 5]}) == [2, 5]


def test_anchor_amounts_take_the_max_per_anchor():
    assert cm.anchor_amounts([('a', 0.0), ('a', 0.7), ('b', 0.2), ('a', 0.3)]) == {'a': 0.7, 'b': 0.2}
    assert cm.anchor_amounts([]) == {}


def test_leader_start_on_anchor_edge_survives_round_off():
    from video_harness.blender_renderer.callout_math import point_in_rect
    rect = [0.834375, 0.8666666896206169, 0.865625, 0.9222222451761725]
    assert point_in_rect([0.85, 0.866666677838171], rect)
    assert not point_in_rect([0.85, 0.8666], rect)
