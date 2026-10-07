from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import video_harness.settings as settings_module
from video_harness.settings import (
    PROJECT_ROOT,
    HarnessSettings,
    VoiceSettings,
    load_project_settings,
    write_project_settings,
)


def write_project_settings_file(path: Path, **updates: object) -> HarnessSettings:
    payload = HarnessSettings().model_dump(mode="python")
    for group, values in updates.items():
        assert isinstance(values, dict)
        payload[group].update(values)
    settings = HarnessSettings.model_validate(payload)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return settings


def test_tracked_project_settings_is_complete_and_round_trips(tmp_path):
    source = PROJECT_ROOT / "settings.json"

    # The shared defaults round-trip independently of this machine's private overlay.
    isolated = tmp_path / 'settings.json'
    isolated.write_bytes(source.read_bytes())
    settings = load_project_settings(isolated)

    assert json.loads(source.read_text(encoding="utf-8")) == settings.model_dump(
        mode="json"
    )


def test_voice_consistency_controls_have_recommended_defaults():
    voice = VoiceSettings()

    assert voice.speaking_rate == 1.0
    assert voice.emotion_mode == "off"
    assert voice.sentence_leading_margin_ms == 100
    assert voice.sentence_trailing_margin_ms == 950
    assert voice.temperature == 0.5
    assert voice.target_syllables_per_second == 5.2
    assert voice.max_internal_pause_ms == 350


def test_voice_consistency_controls_accept_supported_alternatives():
    voice = VoiceSettings(
        emotion_mode="off",
        sentence_leading_margin_ms=0,
        sentence_trailing_margin_ms=800,
    )

    assert voice.emotion_mode == "off"
    assert voice.sentence_leading_margin_ms == 0
    assert voice.sentence_trailing_margin_ms == 800


@pytest.mark.parametrize(
    ("updates", "field"),
    [
        ({"speed_mode": "unstable"}, "speed_mode"),
        ({"emotion_mode": "automatic"}, "emotion_mode"),
        ({"sentence_leading_margin_ms": 301}, "sentence_leading_margin_ms"),
        ({"sentence_trailing_margin_ms": 199}, "sentence_trailing_margin_ms"),
        ({"sentence_trailing_margin_ms": 1501}, "sentence_trailing_margin_ms"),
        ({"target_syllables_per_second": 3.99}, "target_syllables_per_second"),
        ({"target_syllables_per_second": 7.01}, "target_syllables_per_second"),
        ({"max_internal_pause_ms": 49}, "max_internal_pause_ms"),
        ({"max_internal_pause_ms": 801}, "max_internal_pause_ms"),
    ],
)
def test_voice_consistency_controls_reject_unsupported_values(
    updates: dict[str, object],
    field: str,
):
    with pytest.raises(ValidationError, match=field):
        VoiceSettings(**updates)


@pytest.mark.parametrize('pause_ms', [50, 100, 149, 800])
def test_internal_pause_accepts_supported_range(pause_ms):
    assert VoiceSettings(max_internal_pause_ms=pause_ms).max_internal_pause_ms == pause_ms


def test_project_settings_load_complete_json(tmp_path: Path):
    source = tmp_path / "settings.json"
    expected = write_project_settings_file(
        source,
        voice={"temperature": 0.8},
        local_video={"scene_gap_seconds": 0.75},
    )

    assert load_project_settings(source) == expected


def test_project_settings_missing_file_fails_with_remediation(tmp_path: Path):
    source = tmp_path / "settings.json"

    with pytest.raises(FileNotFoundError, match="settings-ui"):
        load_project_settings(source)


def test_project_settings_rejects_malformed_json(tmp_path: Path):
    source = tmp_path / "settings.json"
    source.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid settings JSON"):
        load_project_settings(source)


def test_project_settings_rejects_extra_keys(tmp_path: Path):
    source = tmp_path / "settings.json"
    payload = HarnessSettings().model_dump(mode="json")
    payload["voice"]["unexpected"] = True
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="unexpected"):
        load_project_settings(source)


def test_project_settings_rejects_inverted_duration_range(tmp_path: Path):
    source = tmp_path / "settings.json"
    payload = HarnessSettings().model_dump(mode="json")
    payload["voice"]["min_scene_seconds"] = 9
    payload["voice"]["max_scene_seconds"] = 8
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="minimum.*maximum"):
        load_project_settings(source)


def test_project_settings_rejects_local_timing_that_cannot_fit_voice_and_gap(
    tmp_path: Path,
):
    source = tmp_path / "settings.json"
    payload = HarnessSettings().model_dump(mode="json")
    payload["voice"]["max_scene_seconds"] = 14.5
    payload["local_video"]["scene_gap_seconds"] = 0.65
    payload["local_video"]["max_scene_seconds"] = 15.0
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="voice maximum.*scene gap.*local maximum"):
        load_project_settings(source)


def test_process_vg_values_do_not_override_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "settings.json"
    expected = write_project_settings_file(source, voice={"temperature": 0.8})
    monkeypatch.setenv("VG_TTS_TEMPERATURE", "0.2")

    assert load_project_settings(source) == expected


def test_write_project_settings_is_atomic(tmp_path: Path):
    source = tmp_path / "settings.json"
    settings = HarnessSettings(voice={"temperature": 0.8})

    written = write_project_settings(settings, source)

    assert written == source
    assert HarnessSettings.model_validate_json(source.read_text(encoding="utf-8")) == settings
    assert not source.with_suffix(".json.tmp").exists()


def test_existing_snapshot_beats_changed_project_json(tmp_path: Path):
    project = tmp_path / "project.json"
    write_project_settings_file(project, voice={"temperature": 0.4})
    first = settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        persist=True,
    )
    write_project_settings_file(project, voice={"temperature": 0.7})

    second = settings_module.resolve_run_settings(tmp_path, settings_file=project)

    assert first.voice.temperature == second.voice.temperature == 0.4


def test_refresh_replaces_snapshot_atomically_from_project_json(tmp_path: Path):
    project = tmp_path / "project.json"
    write_project_settings_file(project, pipeline={"output_mode": "all"})
    settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        persist=True,
    )
    write_project_settings_file(project, pipeline={"output_mode": "video_only"})

    refreshed = settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        refresh=True,
        persist=True,
    )

    assert refreshed.pipeline.output_mode == "video_only"
    assert HarnessSettings.model_validate_json(
        (tmp_path / "run-settings.json").read_text(encoding="utf-8")
    ) == refreshed


def test_settings_hash_uses_canonical_json():
    settings = HarnessSettings(voice={"temperature": 0.6, "loudness_mode": "leveled"})
    values = settings.model_dump(mode="json")
    # An unused additive control preserves the pre-acting schema-v4 hash.
    # The tempo cap was a fixed 1.25 before it became a setting.
    values['voice'].pop('max_tempo_factor')
    for key in ('pause_mode', 'comma_pause_ms', 'semantic_pause_ms', 'emphasis_pause_ms', 'sentence_pause_ms'):
        values['voice'].pop(key)
    # The legacy text policy is likewise dropped so pre-callout run hashes hold.
    values['local_video'].pop('text_policy')
    values['local_video'].pop('subtitle_languages')
    values['local_video'].pop('localized_delivery', None)
    values['local_video'].pop('camera_transition_seconds', None)
    values.pop('music', None)
    values.pop('promotion', None)
    values.pop("pacing")
    values["local_video"].pop("target_beat_min_seconds")
    values["local_video"].pop("target_beat_max_seconds")
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert settings_module.settings_sha256(settings) == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_cli_overrides_apply_after_snapshot_and_ignore_none(tmp_path: Path):
    project = tmp_path / "project.json"
    write_project_settings_file(project, voice={"temperature": 0.4, "loudness_range_lu": 8.0})
    settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        persist=True,
    )
    write_project_settings_file(project, voice={"temperature": 0.7, "loudness_range_lu": 4.0})

    resolved = settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        cli_overrides={"voice": {"temperature": 0.6, "loudness_range_lu": None}},
    )

    assert resolved.voice.temperature == 0.6
    assert resolved.voice.loudness_range_lu == 8.0


def test_refresh_requires_run_directory():
    with pytest.raises(ValueError, match="run directory"):
        settings_module.resolve_run_settings(None, refresh=True)


def legacy_settings_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "pipeline": {"output_mode": "all", "variant_mode": "four"},
        "voice": {
            "model": "gpt-4o-mini-tts",
            "voice": "coral",
            "instructions": "legacy OpenAI instructions",
            "min_scene_seconds": 5.5,
            "max_scene_seconds": 8.0,
            "workers": 2,
            "retry_attempts": 4,
            "retry_min_wait_seconds": 1.0,
            "retry_max_wait_seconds": 8.0,
        },
        "render": {
            "final_width": 1920,
            "final_height": 1080,
            "final_fps": 30,
            "draft_width": 960,
            "draft_height": 540,
            "draft_fps": 15,
            "x264_preset": "medium",
            "x264_crf": 18,
            "preview_interval_seconds": 0.5,
            "contact_sheet_columns": 8,
        },
        "qa": {
            "max_undeclared_freeze_seconds": 2.0,
            "black_frame_amount_percent": 99.9,
            "black_frame_threshold": 17,
            "audio_packet_tolerance_seconds": 0.05,
            "duration_tolerance_seconds": 0.05,
        },
    }


def apple_settings_payload() -> dict[str, object]:
    payload = legacy_settings_payload()
    payload["schema_version"] = 2
    payload["voice"] = {
        "voice_identifier": "com.apple.voice.compact.ko-KR.Yuna",
        "rate": 0.5,
        "pitch_multiplier": 1.0,
        "volume": 1.0,
        "min_scene_seconds": 5.5,
        "max_scene_seconds": 8.0,
    }
    return payload


def test_schema_v1_snapshot_remains_readable_without_changing_its_hash(tmp_path: Path):
    payload = legacy_settings_payload()
    snapshot = tmp_path / "run-settings.json"
    snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    settings = settings_module.resolve_run_settings(tmp_path)

    assert settings.schema_version == 1
    assert settings.voice.voice == "coral"
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert settings_module.settings_sha256(settings) == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_schema_v2_apple_snapshot_remains_readable(tmp_path: Path):
    payload = apple_settings_payload()
    snapshot = tmp_path / "run-settings.json"
    snapshot.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    settings = settings_module.resolve_run_settings(tmp_path)

    assert isinstance(settings, settings_module.AppleHarnessSettings)
    assert settings.schema_version == 2
    assert settings.voice.voice_identifier.endswith("Yuna")


@pytest.mark.parametrize("old_version", [1, 2])
def test_refresh_explicitly_replaces_historical_snapshot_with_schema_v3(
    tmp_path: Path,
    old_version: int,
):
    project = tmp_path / "project.json"
    write_project_settings_file(project, voice={"temperature": 0.6})
    snapshot = tmp_path / "run-settings.json"
    payload = legacy_settings_payload() if old_version == 1 else apple_settings_payload()
    snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    refreshed = settings_module.resolve_run_settings(
        tmp_path,
        settings_file=project,
        refresh=True,
        persist=True,
    )

    assert refreshed.schema_version == 6
    assert refreshed.voice.temperature == 0.6
    assert json.loads(snapshot.read_text(encoding="utf-8"))["schema_version"] == 6


def test_run_settings_schema_matches_model_regeneration(tmp_path: Path):
    generated = tmp_path / "run-settings.schema.json"

    settings_module.write_settings_schema(generated)

    assert generated.read_bytes() == (
        PROJECT_ROOT / "video_harness/schemas/run-settings.schema.json"
    ).read_bytes()


def test_settings_document_explains_modes_precedence_and_local_voice_setup():
    document = (PROJECT_ROOT / "settings.md").read_text(encoding="utf-8")

    for phrase in (
        "video_only",
        "prompts_only",
        "balanced_only",
        "run-settings.json",
        "--refresh-settings",
        "python -m video_harness settings",
        "Qwen3-TTS",
        "Qwen3-TTS",
    ):
        assert phrase in document


def test_settings_document_explains_ui_json_snapshot_and_fixed_preview():
    document = (PROJECT_ROOT / "settings.md").read_text(encoding="utf-8")

    for phrase in (
        "python -m video_harness settings-ui",
        "settings.json",
        "run-settings.json",
        "--refresh-settings",
        "Qwen3-TTS",
        "384×216",
        "runtime_defaults.py",
        "저장 후 닫기",
    ):
        assert phrase in document


def test_active_operator_docs_do_not_advertise_environment_settings():
    paths = [
        PROJECT_ROOT / "settings.md",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "video_harness/agent/WORKFLOW.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert ".env.example" not in combined
    assert "VG_TTS_" not in combined
    assert "VG_LOCAL_" not in combined
    assert "VG_OUTPUT_MODE" not in combined
    assert "VG_VARIANT_MODE" not in combined


def test_agent_workflow_requires_human_script_feedback_and_explicit_approval():
    bootstrap = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    workflow = (
        PROJECT_ROOT / "video_harness/agent/WORKFLOW.md"
    ).read_text(encoding="utf-8")
    combined = bootstrap + "\n" + workflow

    for phrase in (
        "settings-ui",
        "저장 후 닫기",
        "전체 대본",
        "사람의 피드백",
        "명시적으로 승인",
        "voice",
        "plan-video",
        "produce",
    ):
        assert phrase in combined
    assert combined.index("전체 대본") < combined.index("python -m video_harness voice")
    assert "침묵" in combined
    assert "기존 실행" in combined


def test_text_policy_defaults_to_legacy_and_is_excluded_from_legacy_hash():
    settings = HarnessSettings()
    assert settings.local_video.text_policy == "legacy"
    values = settings.model_dump(mode="json")
    values["local_video"].pop("text_policy")
    values["local_video"].pop("subtitle_languages")
    values["local_video"].pop('localized_delivery', None)
    values['local_video'].pop('camera_transition_seconds', None)
    values['voice'].pop('max_tempo_factor')
    for key in ('pause_mode', 'comma_pause_ms', 'semantic_pause_ms', 'emphasis_pause_ms', 'sentence_pause_ms'):
        values['voice'].pop(key)
    values.pop('music', None)
    values.pop('promotion', None)
    values.pop("pacing")
    values["local_video"].pop("target_beat_min_seconds")
    values["local_video"].pop("target_beat_max_seconds")
    canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert settings_module.settings_sha256(settings) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_keywords_text_policy_changes_hash():
    legacy = HarnessSettings()
    keywords = HarnessSettings(local_video={"text_policy": "keywords"})
    assert keywords.local_video.text_policy == "keywords"
    assert settings_module.settings_sha256(legacy) != settings_module.settings_sha256(keywords)


def test_project_settings_select_subtitles_and_four_languages():
    payload = json.loads((PROJECT_ROOT / "settings.json").read_text(encoding="utf-8"))
    assert payload["local_video"]["text_policy"] == "subtitles"
    assert payload["local_video"]["subtitle_languages"] == "en,ja,zh,es"


def test_subtitles_policy_and_languages_are_hash_excluded_when_unset():
    settings = HarnessSettings()
    assert settings.local_video.subtitle_languages == ""
    values = settings.model_dump(mode="json")
    values["local_video"].pop("text_policy")
    values["local_video"].pop("subtitle_languages")
    values["local_video"].pop('localized_delivery', None)
    values['local_video'].pop('camera_transition_seconds', None)
    values.pop("music", None)
    values.pop("promotion", None)
    values.pop("pacing")
    values["local_video"].pop("target_beat_min_seconds")
    values["local_video"].pop("target_beat_max_seconds")
    values['voice'].pop('max_tempo_factor')
    for key in ('pause_mode', 'comma_pause_ms', 'semantic_pause_ms', 'emphasis_pause_ms', 'sentence_pause_ms'):
        values['voice'].pop(key)
    canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert settings_module.settings_sha256(settings) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_subtitle_languages_change_hash():
    base = HarnessSettings()
    localized = HarnessSettings(local_video={"text_policy": "subtitles", "subtitle_languages": "en,ja"})
    assert localized.local_video.text_policy == "subtitles"
    assert settings_module.settings_sha256(base) != settings_module.settings_sha256(localized)


def test_subtitle_language_list_parses_and_drops_master():
    settings = HarnessSettings(local_video={"subtitle_languages": " en, ja ,zh,,ko,es "})
    assert settings_module.subtitle_language_list(settings) == ["en", "ja", "zh", "es"]
    assert settings_module.subtitle_language_list(HarnessSettings()) == []
