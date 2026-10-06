from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from video_harness import voice
from video_harness.voice_audio import AudioResult, SceneGeneration, SentenceGeneration
from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.settings import (
    AppleHarnessSettings,
    HarnessSettings,
    LegacyHarnessSettings,
    PROJECT_ROOT,
)
from video_harness.voice import (
    duration_is_valid,
    generate_audio,
    parse_scene_ids,
    synthesize_scenes,
)


def fake_generation(scene: Scene) -> SceneGeneration:
    return SceneGeneration(
        narrative_role=scene.narrative_role,
        sample_rate=24000,
        sample_count=144000,
        sentence_leading_margin_ms=60,
        sentence_trailing_margin_ms=200,
        sentences=(
            SentenceGeneration(
                text=scene.narration,
                seed=20260828,
                instruction_sha256=f"{scene.scene_id:064x}",
                sample_count=144000,
                token_count=32,
                processing_time_seconds=1.25,
                peak_memory_usage=1024.0,
            ),
        ),
    )


@dataclass
class FakeSynthesizer:
    durations: dict[int, float]

    def __post_init__(self):
        self.requested_ids: list[int] = []

    def synthesize(
        self,
        scenes: list[Scene],
        destinations: dict[int, Path],
    ) -> list[AudioResult]:
        results = []
        for scene in scenes:
            self.requested_ids.append(scene.scene_id)
            destination = destinations[scene.scene_id]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(f"scene-{scene.scene_id}".encode())
            results.append(
                AudioResult(
                    scene.scene_id,
                    destination,
                    self.durations[scene.scene_id],
                    fake_generation(scene),
                )
            )
        return results


def make_scene(scene_id: int) -> Scene:
    return Scene(
        scene_id=scene_id,
        title=f"장면 {scene_id}",
        narration=f"이것은 {scene_id}번 장면의 테스트 나레이션입니다.",
        narrative_role="HOOK" if scene_id == 1 else "CONTEXT",
        visual_subject=f"대상 {scene_id}",
    )


def make_script(scene_count: int = 3) -> ScriptArtifact:
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="테스트 주제", reason="테스트용"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="예상",
            constraint="제약",
            actual_answer="실제 답",
            mechanism="원리",
            payoff="결말",
        ),
        scenes=[make_scene(index) for index in range(1, scene_count + 1)],
    )


def snapshot_voice_artifacts(run_dir: Path) -> dict[str, bytes]:
    paths = [
        path
        for path in run_dir.rglob("*")
        if path.is_file()
        and (
            path.name in {
                "script.json",
                "duration-report.json",
                "voice-generation-report.json",
            }
            or path.parent.name == "audioFiles"
        )
    ]
    return {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(paths)
    }


class FailOnceOnFourthReplace:
    def __init__(self):
        self.calls = 0

    def __call__(self, source: Path, destination: Path) -> None:
        self.calls += 1
        if self.calls == 4:
            raise OSError("configured publication failure")
        source.replace(destination)


@pytest.mark.parametrize(
    ("duration", "valid"),
    [(5.49, False), (5.5, True), (8.0, True), (8.01, False)],
)
def test_duration_boundaries(duration, valid):
    assert duration_is_valid(duration, 5.5, 8.0) is valid


def test_synthesis_results_follow_scene_order(tmp_path):
    scenes = [make_scene(3), make_scene(1), make_scene(2)]
    synthesizer = FakeSynthesizer({1: 6.1, 2: 5.5, 3: 8.0})

    results = synthesize_scenes(
        scenes,
        tmp_path,
        synthesizer,
        force=False,
    )

    assert [result.scene_id for result in results] == [1, 2, 3]
    assert synthesizer.requested_ids == [1, 2, 3]


def test_synthesis_refuses_to_overwrite_any_scene_without_force(tmp_path):
    scene = make_scene(1)
    existing = tmp_path / "01_장면_1.mp3"
    existing.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        synthesize_scenes(
            [scene],
            tmp_path,
            FakeSynthesizer({1: 6.0}),
            force=False,
        )


def test_generate_audio_targets_requested_scene_and_updates_script(tmp_path):
    script_path = tmp_path / "script.json"
    script_path.write_text(make_script().model_dump_json(indent=2), encoding="utf-8")
    synthesizer = FakeSynthesizer({2: 6.25})

    report = generate_audio(
        script_path,
        scene_ids={2},
        force=True,
        synthesizer=synthesizer,
        duration_reader=lambda path: {"02": 6.25}[path.name[:2]],
    )

    updated = ScriptArtifact.model_validate_json(script_path.read_text(encoding="utf-8"))
    assert synthesizer.requested_ids == [2]
    assert updated.scenes[1].duration_seconds == 6.25
    assert updated.scenes[1].audio_file == "audioFiles/02_장면_2.mp3"
    assert (tmp_path / "audioFiles/02_장면_2.txt").read_text(encoding="utf-8") == (
        "SCENE 02 - 장면 2\n"
        "Narration: 이것은 2번 장면의 테스트 나레이션입니다.\n"
    )
    assert report.valid_scene_ids == [2]
    assert report.invalid_scene_ids == [1, 3]
    saved_report = json.loads((tmp_path / "duration-report.json").read_text())
    assert saved_report["invalid_scene_ids"] == [1, 3]
    generation_report = json.loads(
        (tmp_path / "voice-generation-report.json").read_text(encoding="utf-8")
    )
    assert generation_report["schema_version"] == 1
    assert generation_report["sentence_gap_milliseconds"] == 1050
    assert generation_report["sentence_leading_margin_ms"] == 100
    assert generation_report["sentence_trailing_margin_ms"] == 950
    assert [scene["scene_id"] for scene in generation_report["scenes"]] == [2]
    entry=generation_report["scenes"][0]
    assert entry["engine"]=="qwen3"
    assert entry["speaker"]=="Sohee"
    assert entry["speed_mode"]=="qwen_legacy"
    assert entry["speaking_rate"]==1.0
    assert entry["target_syllables_per_second"]==5.2
    assert entry["emotion_mode"]=="off"
    assert entry["loudness"]["loudness_mode"]=="leveled"
    assert "instructions_file" in entry
    assert entry["sentences"][0]["seed"]==20260828


def test_generate_audio_uses_configured_duration_range(tmp_path):
    script_path = tmp_path / "script.json"
    script_path.write_text(make_script(scene_count=1).model_dump_json(indent=2), encoding="utf-8")
    settings = HarnessSettings(
        voice={"min_scene_seconds": 4.0, "max_scene_seconds": 9.0}
    )

    report = generate_audio(
        script_path,
        force=True,
        synthesizer=FakeSynthesizer({1: 4.5}),
        duration_reader=lambda _: 4.5,
        settings=settings,
    )

    assert report.minimum_seconds == 4.0
    assert report.maximum_seconds == 9.0


def test_duration_failure_publishes_nothing(tmp_path: Path):
    script_path = tmp_path / "script.json"
    script_path.write_text(
        make_script(scene_count=1).model_dump_json(indent=2),
        encoding="utf-8",
    )
    before = snapshot_voice_artifacts(tmp_path)

    with pytest.raises(voice.SceneDurationError) as error:
        generate_audio(
            script_path,
            force=True,
            synthesizer=FakeSynthesizer({1: 14.5}),
            duration_reader=lambda _: 14.5,
            settings=HarnessSettings(),
        )

    assert error.value.report.scenes[0].status == "long"
    assert snapshot_voice_artifacts(tmp_path) == before


def test_publication_failure_restores_mp3_script_sidecar_and_reports(
    tmp_path: Path,
    monkeypatch,
):
    script = make_script(scene_count=1)
    script.scenes[0].audio_file = "audioFiles/01_장면_1.mp3"
    script.scenes[0].duration_seconds = 6.0
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    audio_dir = tmp_path / "audioFiles"
    audio_dir.mkdir()
    (audio_dir / "01_장면_1.mp3").write_bytes(b"old-mp3")
    (audio_dir / "01_장면_1.txt").write_bytes(b"old-sidecar")
    (tmp_path / "duration-report.json").write_bytes(b'{"old": true}\n')
    (tmp_path / "voice-generation-report.json").write_bytes(
        b'{"schema_version": 1, "sentence_gap_milliseconds": 260, "scenes": []}\n'
    )
    before = snapshot_voice_artifacts(tmp_path)
    monkeypatch.setattr(
        voice,
        "_replace_file",
        FailOnceOnFourthReplace(),
        raising=False,
    )

    with pytest.raises(OSError, match="configured publication failure"):
        generate_audio(
            script_path,
            scene_ids={1},
            force=True,
            synthesizer=FakeSynthesizer({1: 6.25}),
            duration_reader=lambda _: 6.25,
            settings=HarnessSettings(),
        )

    assert snapshot_voice_artifacts(tmp_path) == before


def test_partial_generation_merges_existing_generation_report(tmp_path: Path):
    script_path = tmp_path / "script.json"
    script_path.write_text(
        make_script(scene_count=2).model_dump_json(indent=2),
        encoding="utf-8",
    )
    old_scene = {
        "scene_id": 1,
        "model_id": "historical-model",
        "model_revision": "0" * 40,
        "speaker": "Historical",
        "language": "Korean",
        "temperature": 0.7,
        "max_tokens": 100,
        "top_k": 10,
        "top_p": 0.9,
        "repetition_penalty": 1.0,
        "narrative_role": "HOOK",
        "sample_rate": 24000,
        "sample_count": 120000,
        "sentences": [],
    }
    (tmp_path / "voice-generation-report.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sentence_gap_milliseconds": 260,
                "scenes": [old_scene],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    generate_audio(
        script_path,
        scene_ids={2},
        force=True,
        synthesizer=FakeSynthesizer({2: 6.25}),
        duration_reader=lambda path: 6.25 if path.name.startswith("02") else 6.0,
        settings=HarnessSettings(),
    )

    report = json.loads(
        (tmp_path / "voice-generation-report.json").read_text(encoding="utf-8")
    )
    assert [scene["scene_id"] for scene in report["scenes"]] == [1, 2]
    assert report["scenes"][0] == old_scene
    assert report["scenes"][1]["model_id"].startswith("mlx-community/")


def test_voice_parser_leaves_settings_backed_options_unset():
    args=voice.build_parser().parse_args(["script.json"])
    assert args.speaking_rate is None
    assert args.seed is None
    assert args.speaker is None
    assert args.engine is None


def test_voice_parser_accepts_local_voice_overrides():
    args=voice.build_parser().parse_args(["script.json","--model-id","mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16","--speaking-rate","0.95","--max-tokens","3072","--seed","17"])
    assert args.model_id=="mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16"
    assert args.speaking_rate==.95
    assert args.max_tokens==3072
    assert args.seed==17


def test_generate_audio_builds_qwen_synthesizer_from_settings(tmp_path, monkeypatch):
    script_path = tmp_path / "script.json"
    script_path.write_text(
        make_script(scene_count=1).model_dump_json(indent=2),
        encoding="utf-8",
    )
    configured = HarnessSettings(
        voice={"temperature": 0.7, "seed": 17}
    )
    fake = FakeSynthesizer({1: 6.0})
    captured = {}

    def make_synthesizer(settings, *, duration_reader):
        captured["settings"] = settings
        captured["duration_reader"] = duration_reader
        return fake

    monkeypatch.setattr("video_harness.mlx_voice.MLXAudioSynthesizer", make_synthesizer)

    report = generate_audio(
        script_path,
        force=True,
        duration_reader=lambda _: 6.0,
        settings=configured,
    )

    assert report.valid_scene_ids == [1]
    assert captured["settings"] == configured.voice
    assert fake.requested_ids == [1]


def legacy_settings() -> LegacyHarnessSettings:
    return LegacyHarnessSettings(
        voice={
            "model": "gpt-4o-mini-tts",
            "voice": "coral",
            "instructions": "legacy",
            "min_scene_seconds": 5.5,
            "max_scene_seconds": 8.0,
            "workers": 2,
            "retry_attempts": 4,
            "retry_min_wait_seconds": 1.0,
            "retry_max_wait_seconds": 8.0,
        }
    )


def apple_settings() -> AppleHarnessSettings:
    return AppleHarnessSettings()


@pytest.mark.parametrize("historical", [legacy_settings(), apple_settings()])
def test_generate_audio_rejects_historical_settings_until_explicit_refresh(
    tmp_path,
    historical,
):
    script_path = tmp_path / "script.json"
    script_path.write_text(
        make_script(scene_count=1).model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="settings .* --refresh-settings"):
        generate_audio(
            script_path,
            force=True,
            synthesizer=FakeSynthesizer({1: 6.0}),
            duration_reader=lambda _: 6.0,
            settings=historical,
        )


def test_parse_scene_ids_rejects_zero_and_duplicates():
    assert parse_scene_ids("3,1,3") == {1, 3}
    with pytest.raises(ValueError, match="positive"):
        parse_scene_ids("0,2")


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_story_chain", lambda *args, **kwargs: [])
