from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.render import MediaInfo, RenderReport, render_run


TEMPLATES = [
    ("sky-orbit-reveal", "sky-to-orbit"),
    ("retrograde-track", "fixed-sky"),
    ("moving-observer", "earth-pullback"),
    ("sightline-angle", "orbit-three-quarter"),
    ("speed-comparison", "orbit-top"),
    ("earth-overtake", "earth-tracking"),
    ("projection-proof", "projection-three-quarter"),
    ("return-to-direct", "orbit-to-sky"),
]


def prepare_run(run_dir: Path, scene_count: int = 2) -> None:
    script = ScriptArtifact(
        selected_topic=SelectedTopic(title="화성 역행", reason="테스트"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="질문",
            constraint="조건",
            actual_answer="답",
            mechanism="원리",
            payoff="결과",
        ),
        scenes=[
            Scene(
                scene_id=scene_id,
                title=f"장면_{scene_id}",
                narration=f"{scene_id}번 장면입니다.",
                narrative_role="MECHANISM",
                visual_subject="지구와 화성",
                duration_seconds=5.501 + scene_id / 1000,
                audio_file=f"audioFiles/{scene_id:02d}_장면_{scene_id}.mp3",
            )
            for scene_id in range(1, scene_count + 1)
        ],
    )
    (run_dir / "audioFiles").mkdir(parents=True)
    for scene in script.scenes:
        (run_dir / scene.audio_file).write_bytes(b"fake-mp3")
    (run_dir / "script.json").write_text(script.model_dump_json(), encoding="utf-8")
    payload = {
        "schema_version": 1,
        "preset": "mars-retrograde",
        "output": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "physics": {
            "model": "circular-teaching-model",
            "earth_period_days": 365,
            "mars_period_days": 687,
            "earth_orbit_radius": 1,
            "mars_orbit_radius": 1.52,
            "opposition_day": 0,
        },
        "style": {
            "preset": "hybrid-space-explainer",
            "seed": 220826,
            "earth_scale": 0.075,
            "mars_scale": 0.055,
            "show_labels": False,
        },
        "scenes": [
            {
                "scene_id": scene_id,
                "template": TEMPLATES[scene_id - 1][0],
                "simulation_day_start": -35,
                "simulation_day_end": 35,
                "camera": TEMPLATES[scene_id - 1][1],
            }
            for scene_id in range(1, scene_count + 1)
        ],
    }
    (run_dir / "simulation.json").write_text(json.dumps(payload), encoding="utf-8")


@dataclass
class FakeBackend:
    jobs: list[dict] = field(default_factory=list)
    concatenations: list[tuple[float, float, bool]] = field(default_factory=list)

    def check_dependencies(self) -> None:
        return None

    def render_frames(self, job: dict, cache_dir: Path) -> None:
        self.jobs.append(job)
        cache_dir.mkdir(parents=True, exist_ok=True)
        for frame_index in range(job["frame_count"]):
            (cache_dir / f"frame-{frame_index:06d}.png").write_bytes(b"png")

    def encode_original(
        self,
        cache_dir: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo:
        output_path.write_bytes(b"original-mp4")
        return MediaInfo("h264", None, width, height, float(fps), duration_seconds)

    def encode_scene(
        self,
        original_path: Path,
        audio_path: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: int,
        duration_seconds: float,
    ) -> MediaInfo:
        output_path.write_bytes(b"scene-mp4")
        return MediaInfo("h264", "aac", width, height, float(fps), duration_seconds)

    def create_previews(
        self,
        source_path: Path,
        output_directory: Path,
        timestamps: list[float],
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        preview_paths = [
            output_directory / f"{round(timestamp * 1000):04d}ms.png"
            for timestamp in timestamps
        ]
        for preview_path in preview_paths:
            preview_path.write_bytes(b"png")
        return preview_paths

    def concatenate(
        self,
        scene_paths: list[Path],
        output_path: Path,
        *,
        expected_duration: float,
        require_audio: bool,
        transition_seconds: float = 0.0,
        transition_fade_seconds: float = 0.0,
    ) -> MediaInfo:
        self.concatenations.append(
            (transition_seconds, transition_fade_seconds, require_audio)
        )
        output_path.write_bytes(b"final-mp4")
        audio_codec = "aac" if require_audio else None
        return MediaInfo("h264", audio_codec, 960, 540, 30.0, expected_duration)


def test_render_run_creates_draft_scene_videos_and_report(tmp_path):
    prepare_run(tmp_path)
    backend = FakeBackend()

    report = render_run(tmp_path, quality="draft", backend=backend)

    assert isinstance(report, RenderReport)
    assert len(report.scenes) == 2
    assert backend.jobs[0]["output"] == {"width": 384, "height": 216, "fps": 9}
    assert backend.jobs[0]["frame_count"] == 50
    assert (tmp_path / "videoFiles/draft/01_장면_1.mp4").read_bytes() == b"scene-mp4"
    assert (tmp_path / "final-draft.mp4").read_bytes() == b"final-mp4"
    saved = json.loads((tmp_path / "render-report.json").read_text(encoding="utf-8"))
    assert saved["quality"] == "draft"
    assert saved["science_checks"]["physical_orbits_forward"] is True
    assert saved["science_checks"]["projection_reverses_near_opposition"] is True


def test_render_run_preserves_video_only_scenes_and_full_video(tmp_path):
    prepare_run(tmp_path)

    report = render_run(tmp_path, quality="draft", backend=FakeBackend())

    assert (tmp_path / "videoFiles/draft/original/01_장면_1.mp4").is_file()
    assert (tmp_path / "videoFiles/draft/original/02_장면_2.mp4").is_file()
    assert (tmp_path / "video-only-draft.mp4").is_file()
    assert report.scenes[0].original_video_file == (
        "videoFiles/draft/original/01_장면_1.mp4"
    )
    assert report.final_original_file == "video-only-draft.mp4"


def test_render_run_uses_configured_dip_to_black_for_final_assembly(tmp_path):
    prepare_run(tmp_path)
    backend = FakeBackend()

    render_run(tmp_path, quality="draft", backend=backend)

    assert backend.concatenations == [
        (0.65, 0.15, False),
        (0.65, 0.15, True),
    ]


def test_render_run_creates_scene_previews_at_the_default_interval(tmp_path):
    prepare_run(tmp_path, scene_count=1)

    report = render_run(tmp_path, backend=FakeBackend())

    preview_dir = tmp_path / "videoFiles/previews/01_장면_1"
    assert sorted(path.name for path in preview_dir.glob("*.png")) == [
        "0000ms.png",
        "0500ms.png",
        "1000ms.png",
        "1500ms.png",
        "2000ms.png",
        "2500ms.png",
        "3000ms.png",
        "3500ms.png",
        "4000ms.png",
        "4500ms.png",
        "5000ms.png",
        "5500ms.png",
    ]
    assert report.scenes[0].preview_files == [
        "videoFiles/previews/01_장면_1/0000ms.png",
        "videoFiles/previews/01_장면_1/0500ms.png",
        "videoFiles/previews/01_장면_1/1000ms.png",
        "videoFiles/previews/01_장면_1/1500ms.png",
        "videoFiles/previews/01_장면_1/2000ms.png",
        "videoFiles/previews/01_장면_1/2500ms.png",
        "videoFiles/previews/01_장면_1/3000ms.png",
        "videoFiles/previews/01_장면_1/3500ms.png",
        "videoFiles/previews/01_장면_1/4000ms.png",
        "videoFiles/previews/01_장면_1/4500ms.png",
        "videoFiles/previews/01_장면_1/5000ms.png",
        "videoFiles/previews/01_장면_1/5500ms.png",
    ]


def test_render_run_refuses_to_overwrite_scene_without_force(tmp_path):
    prepare_run(tmp_path)
    output = tmp_path / "videoFiles/01_장면_1.mp4"
    output.parent.mkdir()
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="--force"):
        render_run(tmp_path, scene_ids={1}, backend=FakeBackend())


def test_render_run_rejects_missing_audio_before_backend_work(tmp_path):
    prepare_run(tmp_path)
    (tmp_path / "audioFiles/01_장면_1.mp3").unlink()
    backend = FakeBackend()

    with pytest.raises(FileNotFoundError, match="01_장면_1.mp3"):
        render_run(tmp_path, backend=backend)

    assert backend.jobs == []


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_legacy_render_gate", lambda *args, **kwargs: [])
