import pytest
from video_harness.text_labels import (
    Label, parse_labels, sentence_like, beat_label_issues, plan_text_issues, format_labels_line,
)


def beat(**options):
    return {'beat_id': 'B01', 'start_frame': 0, 'end_frame': 30, 'simulation_time_start': 0,
            'simulation_time_end': 1, 'controller': 'c', 'patch_targets': ['geometry'],
            'controller_options': options}


def local(*beats):
    return {'sequences': [{'sequence_id': 'SEQ01', 'renderer': 'blender', 'duration_frames': 30, 'timeline': list(beats)}]}


def test_keyword_labels_parse_with_defaults():
    labels = parse_labels({'labels': [{'text': '흑운모', 'anchor': 'biotite'}]})
    assert labels == [Label(text='흑운모', anchor='biotite')]
    assert labels[0].side == 'right' and labels[0].emphasis == 'glow' and labels[0].kind == 'word'


@pytest.mark.parametrize('text', ['20종 → 다양한 조합', '사슬 · 고리 · 가지', '순서는 어디에?', '배열 순서는', '다시 접힌다', 'A↔T'])
def test_sentence_like_phrases_are_rejected(text):
    assert sentence_like(text)


@pytest.mark.parametrize('text', ['와도', '바다', '높이', '흑운모', '아미노산 사슬', 'SiO₄'])
def test_single_word_ending_with_particle_shape_passes(text):
    assert not sentence_like(text)


def test_word_longer_than_eight_chars_fails_but_formula_is_exempt():
    assert any(i.startswith('label_text_too_long') for i in beat_label_issues('B01', {'labels': [{'text': '아홉글자짜리라벨임', 'anchor': 'a'}]}))
    assert beat_label_issues('B01', {'labels': [{'text': 'E = h·ν', 'anchor': 'a', 'kind': 'formula'}]}) == []


def test_more_than_two_counted_labels_fail_but_units_do_not_count():
    three = [{'text': f'단어{i}', 'anchor': 'a'} for i in range(3)]
    assert any(i.startswith('label_count_exceeded') for i in beat_label_issues('B01', {'labels': three}))
    two_plus_units = [{'text': '단어1', 'anchor': 'a'}, {'text': '단어2', 'anchor': 'a'}] + [{'text': 'km', 'anchor': 'a', 'kind': 'unit'} for _ in range(4)]
    assert beat_label_issues('B01', {'labels': two_plus_units}) == []
    five_units = [{'text': 'km', 'anchor': 'a', 'kind': 'unit'} for _ in range(5)]
    assert any(i.startswith('label_count_exceeded') for i in beat_label_issues('B01', {'labels': five_units}))


def test_invalid_side_kind_or_empty_anchor_are_field_errors():
    issues = beat_label_issues('B01', {'labels': [{'text': '단어', 'anchor': '', 'side': 'middle'}]})
    assert issues and all(i.startswith('label_field_invalid') for i in issues)


def test_quoted_phrase_hidden_in_review_prose_fails():
    issues = beat_label_issues('B01', {'review_framing': "오른쪽에 ‘굽이치는 바람’, 그 아래 큰 글자"})
    assert issues == ["label_hidden_in_prose: B01 review_framing ‘굽이치는 바람’"]
    assert beat_label_issues('B01', {'review_framing': "wide, 지구 강조"}) == []


def test_plan_text_issues_walk_every_beat():
    plan = local(beat(labels=[{'text': '흑운모', 'anchor': 'biotite'}]),
                 {**beat(labels=[{'text': '순서는 어디에?', 'anchor': 'a'}]), 'beat_id': 'B02'})
    issues = plan_text_issues(plan)
    assert len(issues) == 1 and issues[0].startswith('label_text_sentence: SEQ01/B02')


def test_format_labels_line():
    assert format_labels_line({}) == '없음'
    assert format_labels_line({'labels': [{'text': '흑운모', 'anchor': 'biotite', 'side': 'top'}, {'text': 'SiO₄', 'anchor': 't0', 'kind': 'formula'}]}) == '흑운모 → biotite (top, glow); SiO₄ → t0 (right, glow, formula)'


import json
from video_harness.creative_gates import require_text_plan, text_policy_of


def write_run(tmp_path, policy, *beats):
    (tmp_path / 'run-settings.json').write_text(json.dumps({'schema_version': 4, 'local_video': {'text_policy': policy}}))
    (tmp_path / 'local-sequence-plan.json').write_text(json.dumps(local(*beats), ensure_ascii=False))
    (tmp_path / 'production-plan.json').write_text(json.dumps({'style_bible': {'excluded_elements': ['subtitles']}}))


def test_legacy_runs_skip_the_text_plan_gate(tmp_path):
    write_run(tmp_path, 'legacy', beat(labels=[{'text': '문장입니다.', 'anchor': 'a'}]))
    assert text_policy_of(tmp_path) == 'legacy'
    require_text_plan(tmp_path)
    assert json.loads((tmp_path / 'text-plan-gate.json').read_text())['status'] == 'skipped'


def test_missing_run_settings_counts_as_legacy(tmp_path):
    assert text_policy_of(tmp_path) == 'legacy'


def test_keywords_run_fails_closed_on_sentence_label(tmp_path):
    write_run(tmp_path, 'keywords', beat(labels=[{'text': '문장입니다.', 'anchor': 'a'}]))
    with pytest.raises(ValueError, match='label_text_sentence'):
        require_text_plan(tmp_path)
    assert json.loads((tmp_path / 'text-plan-gate.json').read_text())['status'] == 'failed'


def test_keywords_run_requires_subtitles_excluded_when_labels_exist(tmp_path):
    write_run(tmp_path, 'keywords', beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))
    (tmp_path / 'production-plan.json').write_text(json.dumps({'style_bible': {'excluded_elements': ['logos']}}))
    with pytest.raises(ValueError, match='style_bible_subtitles_allowed'):
        require_text_plan(tmp_path)


def test_keywords_run_passes_with_keyword_labels(tmp_path):
    write_run(tmp_path, 'keywords', beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))
    require_text_plan(tmp_path)
    assert json.loads((tmp_path / 'text-plan-gate.json').read_text())['status'] == 'passed'


from video_harness.text_labels import render_text_issues


def camera():
    return {'position': [0, 0, 20], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'projection': 'ORTHO',
            'ortho_scale': 16, 'lens': 50, 'sensor_width': 36}


def sample(frame, callouts, actors=None, tracked=None):
    actors = actors or {'a': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True}}
    tracked = list(actors) if tracked is None else tracked
    return {'canonical_frame': frame, 'continuity': {'camera': camera(), 'actors': actors, 'paths': {}},
            'entity_scales': {name: 1.0 for name in tracked}, 'callouts': callouts}


def callout(text='흑운모', anchor='a', rect=(.6, .45, .8, .55), leader=((.53, .5), (.6, .5), (.6, .5)), amount=1.0):
    return {'text': text, 'anchor': anchor, 'kind': 'word', 'rect': list(rect), 'leader': [list(p) for p in leader], 'amount': amount}


def keyword_plan():
    return local(beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))


def test_clean_callout_passes():
    assert render_text_issues(keyword_plan(), {'SEQ01': [sample(15, [callout()])]}, width=1920, height=1080) == []


def test_clipped_and_overlapping_labels_fail():
    clipped = sample(15, [callout(rect=(.9, .45, 1.1, .55))])
    assert any(i.startswith('label_clipped') for i in render_text_issues(keyword_plan(), {'SEQ01': [clipped]}, width=1920, height=1080))
    overlapping = sample(15, [callout(), callout(text='석영', rect=(.7, .5, .9, .6))])
    assert any(i.startswith('label_overlap') for i in render_text_issues(keyword_plan(), {'SEQ01': [overlapping]}, width=1920, height=1080))


def test_label_covering_a_non_anchor_object_fails_but_anchor_overlap_is_allowed():
    actors = {'a': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True},
              'b': {'position': [3, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True}}
    covering = sample(15, [callout(rect=(.62, .45, .82, .55))], actors)   # b projects to x≈0.6875
    assert any(i.startswith('label_covers_object') for i in render_text_issues(keyword_plan(), {'SEQ01': [covering]}, width=1920, height=1080))
    over_anchor = sample(15, [callout(rect=(.45, .45, .55, .55), leader=((.5, .5), (.5, .5), (.5, .5)))])
    assert not any(i.startswith('label_covers_object') for i in render_text_issues(keyword_plan(), {'SEQ01': [over_anchor]}, width=1920, height=1080))


def test_leader_start_must_touch_anchor_projection():
    detached = sample(15, [callout(leader=((.2, .2), (.6, .5), (.6, .5)))])
    assert any(i.startswith('leader_detached') for i in render_text_issues(keyword_plan(), {'SEQ01': [detached]}, width=1920, height=1080))


def test_missing_callouts_for_declared_labels_fail():
    no_callouts = {'canonical_frame': 15, 'continuity': {'camera': camera(), 'actors': {}, 'paths': {}}}
    assert any(i.startswith('label_not_rendered') for i in render_text_issues(keyword_plan(), {'SEQ01': [no_callouts]}, width=1920, height=1080))
    faded = sample(15, [callout(amount=0.2)])
    assert any(i.startswith('label_not_rendered') for i in render_text_issues(keyword_plan(), {'SEQ01': [faded]}, width=1920, height=1080))


def test_invisible_labels_are_ignored_and_behind_camera_is_reported():
    hidden = sample(15, [callout(amount=0.0, rect=(.9, .45, 1.1, .55)), callout()])
    assert not any(i.startswith('label_clipped') for i in render_text_issues(keyword_plan(), {'SEQ01': [hidden]}, width=1920, height=1080))
    behind = sample(15, [callout()], {'a': {'position': [0, 0, 25], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True}})
    behind['continuity']['camera']['projection'] = 'PERSP'
    assert any(i.startswith('label_anchor_behind_camera') for i in render_text_issues(keyword_plan(), {'SEQ01': [behind]}, width=1920, height=1080))


def test_require_text_render_reads_reports_and_skips_legacy(tmp_path):
    from video_harness.creative_gates import require_text_render
    write_run(tmp_path, 'keywords', beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))
    report_dir = tmp_path / 'videoFiles/sequences/draft'; report_dir.mkdir(parents=True)
    (report_dir / 'SEQ01-frame-report.json').write_text(json.dumps({'width': 384, 'height': 216, 'state_samples': [sample(15, [callout()])]}))
    require_text_render(tmp_path, tmp_path, 'draft')
    assert json.loads((tmp_path / 'text-draft-gate.json').read_text())['status'] == 'passed'
    (report_dir / 'SEQ01-frame-report.json').write_text(json.dumps({'width': 384, 'height': 216, 'state_samples': [sample(15, [callout(rect=(.9, .45, 1.1, .55))])]}))
    with pytest.raises(ValueError, match='label_clipped'):
        require_text_render(tmp_path, tmp_path, 'draft')
    (tmp_path / 'preview-report.json').write_text(json.dumps({'width': 384, 'height': 216, 'sequences': [{'sequence_id': 'SEQ01', 'state_samples': [sample(15, [callout()])]}]}))
    require_text_render(tmp_path, tmp_path, 'preview')
    assert json.loads((tmp_path / 'text-preview-gate.json').read_text())['status'] == 'passed'
    write_run(tmp_path, 'legacy', beat())
    require_text_render(tmp_path, tmp_path, 'final')
    assert json.loads((tmp_path / 'text-final-gate.json').read_text())['status'] == 'skipped'


def test_untracked_backdrop_actors_do_not_count_as_covered_objects():
    actors = {'a': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True},
              'backdrop': {'position': [0, 0, -5], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 40, 'visible': True}}
    row = sample(15, [callout()], actors, tracked=['a'])
    assert not any(i.startswith('label_covers_object') for i in render_text_issues(keyword_plan(), {'SEQ01': [row]}, width=1920, height=1080))
    tracked_backdrop = sample(15, [callout()], actors, tracked=['a', 'backdrop'])
    assert any(i.startswith('label_covers_object') for i in render_text_issues(keyword_plan(), {'SEQ01': [tracked_backdrop]}, width=1920, height=1080))


def test_keywords_run_requires_callout_layer_even_without_labels():
    no_labels = local(beat())
    bare = {'canonical_frame': 15, 'continuity': {'camera': camera(), 'actors': {}, 'paths': {}}, 'entity_scales': {}}
    issues = render_text_issues(no_labels, {'SEQ01': [bare]}, width=1920, height=1080)
    assert issues and issues[0].startswith('callouts_missing: SEQ01')
    assert render_text_issues(no_labels, {'SEQ01': [sample(15, [])]}, width=1920, height=1080) == []


def test_subtitles_policy_rejects_any_labels():
    plan = local(beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))
    issues = plan_text_issues(plan, policy='subtitles')
    assert issues and issues[0].startswith('labels_forbidden: SEQ01/B01')
    assert plan_text_issues(local(beat()), policy='subtitles') == []


def test_subtitles_policy_rejects_visible_callouts_and_font_actors():
    plan = local(beat())
    with_callout = sample(15, [callout()])
    issues = render_text_issues(plan, {'SEQ01': [with_callout]}, width=1920, height=1080, policy='subtitles')
    assert any(i.startswith('callouts_forbidden: SEQ01') for i in issues)
    font_actors = {'a': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True, 'kind': 'MESH'},
                   '제목': {'position': [0, 2, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True, 'kind': 'FONT'}}
    row = {'canonical_frame': 15, 'continuity': {'camera': camera(), 'actors': font_actors, 'paths': {}}, 'entity_scales': {'a': 1.0}}
    issues = render_text_issues(plan, {'SEQ01': [row]}, width=1920, height=1080, policy='subtitles')
    assert issues == ["on_screen_text_found: SEQ01 frame 15 '제목'"]
    font_actors['제목']['visible'] = False
    assert render_text_issues(plan, {'SEQ01': [row]}, width=1920, height=1080, policy='subtitles') == []


def test_subtitles_policy_skips_callout_layer_requirement():
    bare = {'canonical_frame': 15, 'continuity': {'camera': camera(), 'actors': {}, 'paths': {}}, 'entity_scales': {}}
    assert render_text_issues(local(beat()), {'SEQ01': [bare]}, width=1920, height=1080, policy='subtitles') == []


def test_subtitles_run_gates_use_policy(tmp_path):
    write_run(tmp_path, 'subtitles', beat(labels=[{'text': '흑운모', 'anchor': 'a'}]))
    with pytest.raises(ValueError, match='labels_forbidden'):
        require_text_plan(tmp_path)
    write_run(tmp_path, 'subtitles', beat())
    require_text_plan(tmp_path)
    report_dir = tmp_path / 'videoFiles/sequences/draft'; report_dir.mkdir(parents=True)
    (report_dir / 'SEQ01-frame-report.json').write_text(json.dumps({'width': 384, 'height': 216, 'state_samples': [sample(15, [callout()])]}))
    from video_harness.creative_gates import require_text_render
    with pytest.raises(ValueError, match='callouts_forbidden'):
        require_text_render(tmp_path, tmp_path, 'draft')


def test_subtitles_policy_fails_closed_for_threejs_sequences_without_text_attestation():
    plan = {'sequences': [{'sequence_id': 'SEQ01', 'renderer': 'threejs', 'duration_frames': 30, 'timeline': [beat()]}]}
    bare = {'canonical_frame': 15, 'continuity': {'camera': camera(), 'actors': {}, 'paths': {}}, 'entity_scales': {}}
    issues = render_text_issues(plan, {'SEQ01': [bare]}, width=1920, height=1080, policy='subtitles')
    assert issues and issues[0].startswith('on_screen_text_unverifiable: SEQ01')
    attested = {**bare, 'canvas_text_calls': 0}
    assert render_text_issues(plan, {'SEQ01': [attested]}, width=1920, height=1080, policy='subtitles') == []


def test_subtitles_policy_allows_only_formula_labels():
    formula = [{'text': 'ζ + f = const', 'anchor': 'a', 'kind': 'formula', 'size': 'small'}]
    assert plan_text_issues(local(beat(labels=formula)), policy='subtitles') == []
    mixed = formula + [{'text': '와도', 'anchor': 'a'}]
    issues = plan_text_issues(local(beat(labels=mixed)), policy='subtitles')
    assert issues and issues[0].startswith('labels_forbidden: SEQ01/B01')
    three = [{'text': f'x{i} = 0', 'anchor': 'a', 'kind': 'formula'} for i in range(3)]
    assert plan_text_issues(local(beat(labels=three)), policy='subtitles')[0].startswith('label_count_exceeded')


def test_subtitles_policy_accepts_declared_formula_callouts_and_their_glyphs():
    formula = 'ζ + f = const'
    plan = local(beat(labels=[{'text': formula, 'anchor': 'a', 'kind': 'formula', 'size': 'small'}]))
    actors = {'a': {'position': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': 1, 'visible': True, 'kind': 'MESH'}}
    for name in (formula, formula + ' outline', formula + '.001', formula + '.001 outline'):
        actors[name] = {'position': [4, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': [1, 1, 1], 'radius': .1, 'visible': True, 'kind': 'FONT'}
    shown = {**callout(text=formula), 'kind': 'formula'}
    row = sample(15, [shown], actors=actors, tracked=['a'])
    assert render_text_issues(plan, {'SEQ01': [row]}, width=1920, height=1080, policy='subtitles') == []
    actors['제목'] = {**actors[formula]}
    issues = render_text_issues(plan, {'SEQ01': [row]}, width=1920, height=1080, policy='subtitles')
    assert issues == ["on_screen_text_found: SEQ01 frame 15 '제목'"]
    word = {**callout(text='와도'), 'kind': 'word'}
    del actors['제목']
    issues = render_text_issues(plan, {'SEQ01': [sample(15, [shown, word], actors=actors, tracked=['a'])]},
                                width=1920, height=1080, policy='subtitles')
    assert any(i.startswith("callouts_forbidden: SEQ01 frame 15 ['와도']") for i in issues)


def test_small_labels_use_the_unit_height():
    from video_harness.blender_renderer.callout_math import text_box
    large = text_box('ζ + f = const', 'formula', 1920, 1080)
    small = text_box('ζ + f = const', 'formula', 1920, 1080, 'small')
    assert small[1] == pytest.approx(large[1] / 2) and small[0] == pytest.approx(large[0] / 2)


def test_subtitles_run_with_formula_labels_keeps_subtitles_in_style(tmp_path):
    write_run(tmp_path, 'subtitles', beat(labels=[{'text': 'ζ+f=const', 'anchor': 'a', 'kind': 'formula', 'size': 'small'}]))
    (tmp_path / 'production-plan.json').write_text(json.dumps({'style_bible': {'excluded_elements': ['logos']}}))
    require_text_plan(tmp_path)
    assert json.loads((tmp_path / 'text-plan-gate.json').read_text())['status'] == 'passed'


def test_state_report_accepts_callout_and_text_attestation_evidence():
    from video_harness.sequence_qa import StateSample
    row = {'canonical_frame': 0, 'simulation_time': 0.0, 'visible_layers': ['x'], 'geometry_operation_keys': ['B01'],
           'camera': {'position': [0, 0, 1], 'target': [0, 0, 0]}, 'entity_scales': {}, 'state_fingerprint': 'f',
           'callouts': [callout(text='ζ+f=const')], 'canvas_text_calls': 0}
    assert StateSample.model_validate(row).callouts[0]['text'] == 'ζ+f=const'
