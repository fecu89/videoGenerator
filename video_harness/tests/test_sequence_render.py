from __future__ import annotations

from video_harness.settings import ArchivedV5HarnessSettings

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from video_harness.media import MediaInfo
from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.performance import PerformanceRecorder
from video_harness.production import script_sha256
from video_harness.sequence_models import OnlinePlan
from video_harness.sequence_render import (
    SequenceRenderReport,
    create_online_references,
    render_sequence_quality,
)
from video_harness.settings import HarnessSettings


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_fake_media(path: Path, info: MediaInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(info), sort_keys=True), encoding="utf-8")


def _read_fake_media(path: Path) -> MediaInfo:
    return MediaInfo(**json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def v2_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "audioFiles").mkdir(parents=True)
    script = ScriptArtifact(
        selected_topic=SelectedTopic(title="연속 장면", reason="렌더 계약"),
        story_engine=StoryEngine(
            common_belief="장면은 끊긴다",
            contradiction="상태는 이어진다",
            obvious_answer="장면마다 다시 그린다",
            constraint="시각 상태를 보존한다",
            actual_answer="시퀀스로 렌더한다",
            mechanism="정수 프레임을 사용한다",
            payoff="경계가 사라진다",
        ),
        scenes=[
            Scene(
                scene_id=1,
                title="첫 장면",
                narration="첫 장면의 음성입니다.",
                narrative_role="HOOK",
                visual_subject="하늘 궤적",
                duration_seconds=6.1,
                audio_file="audioFiles/01_첫_장면.mp3",
            ),
            Scene(
                scene_id=2,
                title="둘째 장면",
                narration="둘째 장면의 음성입니다.",
                narrative_role="MECHANISM",
                visual_subject="궤도",
                duration_seconds=4.0,
                audio_file="audioFiles/02_둘째_장면.mp3",
            ),
            Scene(
                scene_id=3,
                title="셋째 장면",
                narration="셋째 장면의 음성입니다.",
                narrative_role="PAYOFF",
                visual_subject="투영",
                duration_seconds=3.0,
                audio_file="audioFiles/03_셋째_장면.mp3",
            ),
        ],
    )
    script_path = run_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    for scene in script.scenes:
        (run_dir / scene.audio_file).write_bytes(f"audio-{scene.scene_id}".encode())

    production = {
        "schema_version": 2,
        "script_sha256": script_sha256(script_path),
        "defaults": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "preview_interval_seconds": 0.5,
            "scene_transition": {
                "mode": "dip_to_black",
                "duration_seconds": 0.65,
                "fade_seconds": 0.15,
            },
        },
        "style_bible": {
            "visual_mode": "scientific visualization",
            "entities": [],
            "palette": ["navy", "white"],
            "lighting": "stable",
            "excluded_elements": ["logos"],
        },
        "scenes": [
            {"scene_id": 1, "duration_seconds": 188 / 30, "shots": []},
            {"scene_id": 2, "duration_seconds": 4.0, "shots": []},
            {"scene_id": 3, "duration_seconds": 3.0, "shots": []},
        ],
        "visual_sequences": [
            {"sequence_id": "SEQ01", "scene_ids": [1], "primary_route": "local", "purpose": "궤적", "visual_beat_ids": ["B01"]},
            {"sequence_id": "SEQ02", "scene_ids": [2, 3], "primary_route": "local", "purpose": "연속 궤도", "visual_beat_ids": ["B02", "B03"]},
        ],
        "visual_beats": [
            {"beat_id": "B01", "scene_id": 1, "start_frame": 0, "end_frame": 188, "primary_event": "궤적", "relationship_owner": "simulation"},
            {"beat_id": "B02", "scene_id": 2, "start_frame": 0, "end_frame": 120, "primary_event": "궤도", "relationship_owner": "simulation"},
            {"beat_id": "B03", "scene_id": 3, "start_frame": 120, "end_frame": 210, "primary_event": "투영", "relationship_owner": "simulation"},
        ],
    }
    production_path = run_dir / "production-plan.json"
    _write_json(production_path, production)
    local = {
        "schema_version": 1,
        "script_sha256": script_sha256(script_path),
        "production_plan_sha256": script_sha256(production_path),
        "defaults": {"width": 1920, "height": 1080, "fps": 30},
        "simulation_config_file": "simulation.json",
        "sequences": [
            {
                "sequence_id": "SEQ01",
                "scene_ids": [1],
                "duration_frames": 188,
                "render_mode": "simulation",
                "scene_graph": "mars-retrograde-teaching-model-v2",
                "scene_spans": [
                    {"scene_id": 1, "start_frame": 0, "end_frame": 188, "audio_start_frame": 0, "audio_end_frame": 183, "tail_silence_frames": 5}
                ],
                "timeline": [
                    {"beat_id": "B01", "start_frame": 0, "end_frame": 188, "simulation_time_start": -70.0, "simulation_time_end": 70.0, "controller": "show-same-direction-arrows", "patch_targets": ["geometry", "layers"], "priority": 0}
                ],
            },
            {
                "sequence_id": "SEQ02",
                "scene_ids": [2, 3],
                "duration_frames": 210,
                "render_mode": "simulation",
                "scene_graph": "mars-retrograde-teaching-model-v2",
                "scene_spans": [
                    {"scene_id": 2, "start_frame": 0, "end_frame": 120, "audio_start_frame": 0, "audio_end_frame": 120, "tail_silence_frames": 0},
                    {"scene_id": 3, "start_frame": 120, "end_frame": 210, "audio_start_frame": 120, "audio_end_frame": 210, "tail_silence_frames": 0},
                ],
                "timeline": [
                    {"beat_id": "B02", "start_frame": 0, "end_frame": 120, "simulation_time_start": 70.0, "simulation_time_end": 100.0, "controller": "grow-speed-trails", "patch_targets": ["geometry", "layers"], "priority": 0},
                    {"beat_id": "B03", "start_frame": 120, "end_frame": 210, "simulation_time_start": 100.0, "simulation_time_end": 130.0, "controller": "track-local-overtake", "patch_targets": ["geometry", "camera"], "priority": 0},
                ],
            },
        ],
    }
    _write_json(run_dir / "local-sequence-plan.json", local)
    online = {
        "schema_version": 1,
        "script_sha256": script_sha256(script_path),
        "production_plan_sha256": script_sha256(production_path),
        "shots": [
            {
                "online_shot_id": "ON-B01", "beat_ids": ["B01"], "scene_ids": [1],
                "source_sequence_id": "SEQ01", "source_start_frame": 10, "source_end_frame": 100,
                "duration_seconds": 3.0, "short_shot_reason": "정밀 궤적 참조",
                "preferred_mode": "v2v", "science_authority": "local_reference",
                "primary_event": "궤적", "invariants": ["관계 유지"],
                "reference_video_file": "videoFiles/onlineReferences/ON-B01.mp4",
                "prompt_file": "videoFiles/prompts/online/SEQ01/ON-B01.txt",
                "metadata_file": "videoFiles/prompts/online/SEQ01/ON-B01.json"
            },
            {
                "online_shot_id": "ON-B02-B03", "beat_ids": ["B02", "B03"], "scene_ids": [2, 3],
                "source_sequence_id": "SEQ02", "source_start_frame": 0, "source_end_frame": 210,
                "duration_seconds": 7.0, "preferred_mode": "v2v", "science_authority": "local_reference",
                "primary_event": "연속 궤도", "invariants": ["관계 유지"],
                "reference_video_file": "videoFiles/onlineReferences/ON-B02-B03.mp4",
                "prompt_file": "videoFiles/prompts/online/SEQ02/ON-B02-B03.txt",
                "metadata_file": "videoFiles/prompts/online/SEQ02/ON-B02-B03.json"
            },
        ],
    }
    _write_json(run_dir / "online-plan.json", online)
    _write_json(
        run_dir / "simulation.json",
        {
            "schema_version": 1,
            "preset": "mars-retrograde",
            "output": {"width": 1920, "height": 1080, "fps": 30, "video_codec": "h264", "audio_codec": "aac"},
            "physics": {"model": "circular-teaching-model", "earth_period_days": 365.0, "mars_period_days": 687.0, "earth_orbit_radius": 1.0, "mars_orbit_radius": 1.52, "opposition_day": 0.0},
            "style": {"preset": "hybrid-space-explainer", "seed": 7, "earth_scale": 0.075, "mars_scale": 0.055, "show_labels": False},
            "scenes": [
                {"scene_id": 1, "template": "retrograde-track", "simulation_day_start": -70.0, "simulation_day_end": 70.0, "camera": "fixed-sky"},
                {"scene_id": 2, "template": "speed-comparison", "simulation_day_start": 70.0, "simulation_day_end": 100.0, "camera": "orbit-top"},
                {"scene_id": 3, "template": "projection-proof", "simulation_day_start": 100.0, "simulation_day_end": 130.0, "camera": "projection-three-quarter"},
            ],
        },
    )
    return run_dir


@dataclass
class FakeSequenceBackend:
    version: str = "fake-v1"
    jobs: list[dict[str, object]] = field(default_factory=list)
    concat_inputs: list[Path] = field(default_factory=list)
    narrated_concat_inputs: list[Path] = field(default_factory=list)
    concat_calls: list[dict[str, object]] = field(default_factory=list)
    extracts: list[tuple[Path, Path, int, int, int]] = field(default_factory=list)
    muxes: list[tuple[Path, list[tuple[Path, int, int]], Path]] = field(default_factory=list)

    def check_dependencies(self) -> None:
        return None

    def render_frames(self, job: dict[str, object], cache_dir: Path) -> Path:
        self.jobs.append(job)
        cache_dir.mkdir(parents=True, exist_ok=True)
        frame_count = int(job["frame_count"])
        frames = []
        for index in range(frame_count):
            frame = cache_dir / f"frame-{index:06d}.png"
            frame.write_bytes(b"png")
            frames.append(str(frame))
        report = cache_dir / "frame-report.json"
        _write_json(
            report,
            {
                "sequence_id": job["sequence_id"],
                "frame_count": frame_count,
                "width": job["output"]["width"],
                "height": job["output"]["height"],
                "frames": frames,
                "state_samples": [],
                "backend": {
                    "requested": "metal",
                    "actual": "metal",
                    "vendor": "Apple",
                    "renderer": "ANGLE Metal Renderer: Apple M1",
                },
                "timings": {
                    "frame_count": frame_count,
                    "render_ms": 1.0,
                    "capture_ms": 2.0,
                    "write_ms": 3.0,
                    "total_ms": 6.0,
                },
            },
        )
        return report


@pytest.fixture
def fake_sequence_backend(monkeypatch: pytest.MonkeyPatch) -> FakeSequenceBackend:
    backend = FakeSequenceBackend()

    def fake_info(spec, *, audio: bool) -> MediaInfo:
        return MediaInfo("h264", "aac" if audio else None, spec.width, spec.height, float(spec.fps), spec.frame_count / spec.fps, spec.frame_count, "yuv420p")

    def fake_encode(_pattern: Path, destination: Path, spec, **_kwargs):
        info = fake_info(spec, audio=False)
        _write_fake_media(destination, info)
        return info

    def fake_mux(video: Path, placements, destination: Path, spec, **_kwargs):
        backend.muxes.append((video, [(item.source, item.start_frame, item.end_frame) for item in placements], destination))
        info = fake_info(spec, audio=True)
        _write_fake_media(destination, info)
        return info

    def fake_extract(source: Path, destination: Path, *, start_frame: int, end_frame: int, fps: int, **_kwargs):
        backend.extracts.append((source, destination, start_frame, end_frame, fps))
        source_info = _read_fake_media(source)
        info = MediaInfo(
            "h264",
            None,
            source_info.width,
            source_info.height,
            float(fps),
            (end_frame - start_frame) / fps,
            end_frame - start_frame,
            "yuv420p",
        )
        _write_fake_media(destination, info)
        return info

    def fake_concat(inputs, destination: Path, *, expected_duration: float, require_audio: bool, **_kwargs):
        paths = list(inputs)
        backend.concat_calls.append(
            {
                "inputs": paths,
                "expected_duration": expected_duration,
                "require_audio": require_audio,
                **_kwargs,
            }
        )
        if require_audio:
            backend.narrated_concat_inputs = paths
        else:
            backend.concat_inputs = paths
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"final")
        return MediaInfo("h264", "aac" if require_audio else None, 1920, 1080, 30.0, expected_duration)

    monkeypatch.setattr("video_harness.sequence_render.encode_frames", fake_encode)
    monkeypatch.setattr("video_harness.sequence_render.mux_audio_timeline", fake_mux)
    monkeypatch.setattr("video_harness.sequence_render.extract_video_segment", fake_extract)
    monkeypatch.setattr("video_harness.sequence_render.concat_videos", fake_concat)
    return backend


def test_scene_slices_use_half_open_scene_spans(fake_sequence_backend, v2_run):
    report = render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)

    first = report.sequences[0].scene_slices[0]
    assert first.start_frame == 0
    assert first.end_frame == 188
    assert first.frame_count == 188


def test_render_records_python_stages_and_normalized_renderer_telemetry(
    fake_sequence_backend, v2_run
):
    """Removing the recorder plumbing must not discard renderer attestation."""
    recorder = PerformanceRecorder()

    rendered = render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
        performance=recorder,
    )

    report = recorder.report()
    assert {event.name for event in report.phase_events} >= {
        "renderer",
        "ffmpeg_encode",
        "audio_mux",
        "webgl_render",
        "canvas_capture",
        "frame_write",
    }
    assert [item.sequence_id for item in report.renderer_reports] == ["SEQ01", "SEQ02"]
    assert report.renderer_reports[0].backend.renderer == "ANGLE Metal Renderer: Apple M1"
    assert report.rendered_frame_count == sum(
        result.frame_count for result in rendered.sequences
    )
    assert report.reused_frame_count == 0
    base_counts = report.output_frame_counts["base:final"]
    assert base_counts.rendered_frame_count == report.rendered_frame_count
    assert base_counts.reused_frame_count == 0
    assert base_counts.rendered_sequence_ids == ["SEQ01", "SEQ02"]


def test_renderer_phase_excludes_frame_report_normalization_io(
    monkeypatch: pytest.MonkeyPatch,
    fake_sequence_backend: FakeSequenceBackend,
    v2_run: Path,
):
    """Including report normalization in renderer timing would overstate renderer work."""
    import video_harness.sequence_render as module

    now = [0.0]
    original_render = fake_sequence_backend.render_frames
    original_normalize = module._normalize_frame_report

    def render_frames(job: dict[str, object], cache_dir: Path) -> Path:
        now[0] += 1.0
        return original_render(job, cache_dir)

    def normalize(*args, **kwargs):
        now[0] += 100.0
        return original_normalize(*args, **kwargs)

    monkeypatch.setattr(fake_sequence_backend, "render_frames", render_frames)
    monkeypatch.setattr(module, "_normalize_frame_report", normalize)
    recorder = PerformanceRecorder(clock=lambda: now[0])

    render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
        performance=recorder,
    )

    renderer_events = [
        event.duration_ms
        for event in recorder.report().phase_events
        if event.name == "renderer"
    ]
    assert renderer_events == [1000.0, 1000.0]


def test_cached_base_output_reports_reused_frames(
    fake_sequence_backend: FakeSequenceBackend,
    v2_run: Path,
):
    """Treating a cache hit as zero work must still report the reused frame volume."""
    first = render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
    )
    recorder = PerformanceRecorder()

    render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
        performance=recorder,
    )

    report = recorder.report()
    assert report.rendered_frame_count == 0
    assert report.reused_frame_count == sum(
        result.frame_count for result in first.sequences
    )
    base_counts = report.output_frame_counts["base:final"]
    assert base_counts.rendered_frame_count == 0
    assert base_counts.reused_frame_count == report.reused_frame_count
    assert base_counts.reused_sequence_ids == ["SEQ01", "SEQ02"]


def test_draft_maps_output_frames_without_rewriting_canonical_plan(fake_sequence_backend, v2_run):
    report = render_sequence_quality(v2_run, quality="draft", backend=fake_sequence_backend)

    job = fake_sequence_backend.jobs[0]
    assert job["canonical_fps"] == 30
    assert job["duration_frames"] == 188
    assert job["frame_count"] == 57
    assert job["output"] == {"width": 384, "height": 216, "fps": 9}
    assert job["timeline"][0]["end_frame"] == 188
    assert len(job["canonical_state_cache"]) == 188
    assert report.sequences[0].scene_slices[0].end_frame == 188
    assert report.sequences[0].scene_slices[0].frame_count == 57


def test_draft_sequence_output_uses_resolved_settings(fake_sequence_backend, v2_run):
    settings = ArchivedV5HarnessSettings(
        render={"draft_width": 1280, "draft_height": 720, "draft_fps": 24}
    )

    report = render_sequence_quality(
        v2_run,
        quality="draft",
        backend=fake_sequence_backend,
        settings=settings,
    )

    assert (report.sequences[0].width, report.sequences[0].height, report.sequences[0].fps) == (
        1280,
        720,
        24,
    )


def test_audio_placements_end_before_declared_tail_silence(fake_sequence_backend, v2_run):
    render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)

    master_mux = next(item for item in fake_sequence_backend.muxes if item[2].name == "SEQ01-narrated.mp4")
    assert master_mux[1] == [(v2_run / "audioFiles/01_첫_장면.mp3", 0, 183)]
    scene_mux = next(item for item in fake_sequence_backend.muxes if item[2].name == "01_첫_장면.mp4")
    assert scene_mux[1] == [(v2_run / "audioFiles/01_첫_장면.mp3", 0, 183)]


def test_final_assembly_concatenates_continuous_sequence_masters_without_transition(
    fake_sequence_backend, v2_run
):
    render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)

    assert fake_sequence_backend.concat_inputs == [
        v2_run / "videoFiles/sequences/final/SEQ01.mp4",
        v2_run / "videoFiles/sequences/final/SEQ02.mp4",
    ]
    # AAC priming must not be concatenated at every sequence boundary.
    assert fake_sequence_backend.narrated_concat_inputs == []
    final_mux = next(item for item in fake_sequence_backend.muxes if item[2] == v2_run / "final.mp4")
    assert final_mux[0] == v2_run / "video-only.mp4"
    assert final_mux[1] == [
        (v2_run / "audioFiles/01_첫_장면.mp3", 0, 183),
        (v2_run / "audioFiles/02_둘째_장면.mp3", 188, 308),
        (v2_run / "audioFiles/03_셋째_장면.mp3", 308, 398),
    ]
    assert [(call["transition_seconds"], call["transition_fade_seconds"])
            for call in fake_sequence_backend.concat_calls] == [(0.0, 0.0)]
    assert [call["expected_duration"] for call in fake_sequence_backend.concat_calls] == [398 / 30]


def test_report_paths_are_relative_to_staged_artifact_root(fake_sequence_backend, v2_run, tmp_path):
    staged = tmp_path / "staged"
    report = render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend, output_root=staged)

    assert report.artifact_root == staged.resolve()
    assert report.sequences[0].master_file == "videoFiles/sequences/final/SEQ01.mp4"
    assert report.sequences[0].state_report_file == "videoFiles/sequences/final/SEQ01-frame-report.json"
    assert not Path(report.sequences[0].scene_slices[0].silent_file).is_absolute()
    assert report.final_file == "final.mp4"


def test_online_references_use_final_half_open_master_ranges(fake_sequence_backend, v2_run):
    report = render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)
    online = OnlinePlan.model_validate_json((v2_run / "online-plan.json").read_text(encoding="utf-8"))

    references = create_online_references(v2_run, online, report)

    assert references == [
        "videoFiles/onlineReferences/ON-B01.mp4",
        "videoFiles/onlineReferences/ON-B02-B03.mp4",
    ]
    assert fake_sequence_backend.extracts[-2:] == [
        (v2_run / "videoFiles/sequences/final/SEQ01.mp4", v2_run / "videoFiles/onlineReferences/ON-B01.mp4", 10, 100, 30),
        (v2_run / "videoFiles/sequences/final/SEQ02.mp4", v2_run / "videoFiles/onlineReferences/ON-B02-B03.mp4", 0, 210, 30),
    ]


def test_online_references_reject_draft_report(fake_sequence_backend, v2_run):
    report = render_sequence_quality(v2_run, quality="draft", backend=fake_sequence_backend)
    online = OnlinePlan.model_validate_json((v2_run / "online-plan.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="final"):
        create_online_references(v2_run, online, report)


def test_matching_render_record_reuses_sequence_artifacts(fake_sequence_backend, v2_run):
    first = render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)
    initial_job_count = len(fake_sequence_backend.jobs)
    initial_mux_count = len(fake_sequence_backend.muxes)
    initial_concat_count = len(fake_sequence_backend.concat_calls)
    second = render_sequence_quality(v2_run, quality="final", backend=fake_sequence_backend)

    assert second == first
    assert len(fake_sequence_backend.jobs) == initial_job_count
    assert len(fake_sequence_backend.muxes) == initial_mux_count + 1
    assert len(fake_sequence_backend.concat_calls) == initial_concat_count + 1


def test_forced_draft_does_not_replace_reusable_final_scene_slices(
    fake_sequence_backend,
    v2_run,
):
    first_final = render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
    )
    final_slice_paths = [
        v2_run / relative
        for sequence in first_final.sequences
        for scene_slice in sequence.scene_slices
        for relative in (scene_slice.silent_file, scene_slice.narrated_file)
    ]
    final_slice_bytes = {path: path.read_bytes() for path in final_slice_paths}

    draft = render_sequence_quality(
        v2_run,
        quality="draft",
        backend=fake_sequence_backend,
        force=True,
    )

    assert {path: path.read_bytes() for path in final_slice_paths} == final_slice_bytes
    draft_slice_files = {
        relative
        for sequence in draft.sequences
        for scene_slice in sequence.scene_slices
        for relative in (scene_slice.silent_file, scene_slice.narrated_file)
    }
    assert all(
        scene_slice.silent_file.startswith("videoFiles/draft/original/")
        and scene_slice.narrated_file.startswith("videoFiles/draft/")
        for sequence in draft.sequences
        for scene_slice in sequence.scene_slices
    )
    assert draft_slice_files.isdisjoint(
        path.relative_to(v2_run).as_posix() for path in final_slice_paths
    )

    final_job_count = len(fake_sequence_backend.jobs)
    third_final = render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
    )

    assert len(fake_sequence_backend.jobs) == final_job_count
    for sequence in third_final.sequences:
        assert (sequence.width, sequence.height, sequence.fps) == (1920, 1080, 30)
        for scene_slice in sequence.scene_slices:
            for relative in (scene_slice.silent_file, scene_slice.narrated_file):
                media = _read_fake_media(v2_run / relative)
                assert (media.width, media.height, media.fps, media.frame_count) == (
                    sequence.width,
                    sequence.height,
                    float(sequence.fps),
                    scene_slice.frame_count,
                )


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_creative_plan", lambda *args, **kwargs: [])
