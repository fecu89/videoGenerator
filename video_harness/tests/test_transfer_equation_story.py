import json
from pathlib import Path

import pytest
from video_harness.blender_renderer.transfer_equation_story_math import (
    SOURCE, beam_intensities, lane_plan, sequence_values, state_at, validate_job)


def test_rule_matches_narration_numbers():
    assert sequence_values(72) == pytest.approx([72, 40, 24, 16, 12, 10, 9, 8.5])
    assert sequence_values(0)[1:4] == pytest.approx([4, 6, 7])
    assert SOURCE == 8
    assert sequence_values(8) == pytest.approx([8] * 8)


def test_coin_identities_conserve_and_halve_marked_coins():
    plan = lane_plan(72, blue=True)
    everything = set(plan['initial'])
    for step in plan['steps']:
        assert set(step['kept']) | set(step['removed']) <= everything
        everything |= set(step['added'])
    assert len(plan['steps'][-1]['stack']) == 9 and plan['steps'][-1]['value'] == pytest.approx(8.5)
    blue = [sum(plan['colours'][c] == 'blue' for c in s['stack']) for s in plan['steps']]
    assert blue[:3] == [36, 18, 9] and blue[-1] == 1  # exact tail 0.56 is drawn as a faded coin


def test_beam_uses_the_same_rule_as_the_coins():
    rows = beam_intensities(72)
    assert [r[2] for r in rows][:3] == pytest.approx([40, 24, 16])
    assert rows[0][1] == pytest.approx(36)


def beat(i, start, end, shot, state):
    return dict(beat_id=f'B{i:02d}', start_frame=start, end_frame=end, controller='transfer-equation-story',
                controller_options=dict(camera_shot=shot, state=state))


def test_progress_persists_while_toggles_ease_back():
    job = dict(canonical_fps=30, timeline=[beat(1, 0, 60, 'row_wide', dict(classroom=1, a_start=72, a_progress=7, trail=1)),
                                           beat(2, 60, 120, 'compare_close', dict(classroom=1, compare=1))])
    end = state_at(job, 119)
    assert end['a_progress'] == pytest.approx(7) and end['trail'] == pytest.approx(0)
    assert state_at(job, 59)['trail'] == pytest.approx(1)
    assert state_at(job, 90) == state_at(job, 90)
    assert state_at(job, 70)['prev_shot'] == 'row_wide' and state_at(job, 70)['shot'] == 'compare_close'


def test_marked_run_retires_first_lane_for_good():
    job = dict(canonical_fps=30, timeline=[beat(1, 0, 30, 'row_wide', dict(classroom=1, a_start=72, a_progress=7)),
                                           beat(2, 30, 60, 'desk_close', dict(classroom=1, marked=1, m_progress=1)),
                                           beat(3, 60, 90, 'row_wide', dict(classroom=1))])
    assert state_at(job, 10)['retired_a'] == 0
    assert state_at(job, 59)['retired_a'] == pytest.approx(1)
    assert state_at(job, 89)['retired_a'] == pytest.approx(1)


def test_approved_run_plan_is_a_valid_job():
    run = Path(__file__).resolve().parents[2] / 'runs' / '20260928-015341-전달방정식' / 'local-sequence-plan.json'
    if not run.is_file():
        pytest.skip('run folder not present')
    for sequence in json.loads(run.read_text())['sequences']:
        cache = [dict(canonical_frame=f, simulation_time=f / 30,
                      active_beat_ids=[next(b['beat_id'] for b in sequence['timeline'] if b['start_frame'] <= f < b['end_frame'])])
                 for f in range(sequence['duration_frames'])]
        validate_job(dict(scene_graph=sequence['scene_graph'], frame_count=sequence['duration_frames'],
                          duration_frames=sequence['duration_frames'], canonical_fps=30,
                          output=dict(width=384, height=216, fps=9), timeline=sequence['timeline'],
                          canonical_state_cache=cache))


def test_staged_review_keeps_run_settings(tmp_path):
    from video_harness.creative_gates import stage_creative_reviews
    source, stage = tmp_path / 'run', tmp_path / 'stage'
    source.mkdir(); stage.mkdir()
    for name in ('story-chain.json', 'continuity-plan.json', 'run-settings.json'):
        (source / name).write_text('{}')
    stage_creative_reviews(source, stage)
    assert (stage / 'run-settings.json').is_file()
