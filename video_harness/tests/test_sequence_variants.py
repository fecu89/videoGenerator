from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness import sequence_render as sequence_render_module
from video_harness.performance import PerformanceRecorder
from video_harness.production import load_production_plan, script_sha256
from video_harness.sequence_plans import load_local_sequence_plan, load_online_plan
from video_harness.sequence_qa import validate_reference_coverage
from video_harness.sequence_render import render_sequence_quality
from video_harness.sequence_variants import assemble_sequence_variants
from video_harness.settings import HarnessSettings
from video_harness.tests.test_sequence_render import (
    FakeSequenceBackend,
    fake_sequence_backend,
    v2_run,
)
from video_harness.variants import SequenceVariantPlan


def _variant_plan(run_dir: Path) -> SequenceVariantPlan:
    payload = {
        "schema_version": 2,
        "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
        "local_sequence_plan_sha256": script_sha256(
            run_dir / "local-sequence-plan.json"
        ),
        "script_sha256": script_sha256(run_dir / "script.json"),
        "variants": [
            {
                "variant_id": "balanced",
                "label": "Balanced",
                "sequence_ids": ["SEQ01", "SEQ02"],
            },
            {
                "variant_id": "explain",
                "label": "Explain",
                "sequence_ids": ["SEQ01", "SEQ02"],
                "overrides": [
                    {
                        "sequence_id": "SEQ02",
                        "layer_timing_profile": "explain",
                        "lighting_profile": "clear",
                    }
                ],
            },
            {
                "variant_id": "dynamic",
                "label": "Dynamic",
                "sequence_ids": ["SEQ01", "SEQ02"],
                "overrides": [
                    {
                        "sequence_id": "SEQ02",
                        "camera_profile": "close",
                        "layer_timing_profile": "dynamic",
                        "scale_profile": "emphasis",
                    }
                ],
            },
            {
                "variant_id": "cinematic",
                "label": "Cinematic",
                "sequence_ids": ["SEQ01", "SEQ02"],
                "overrides": [
                    {
                        "sequence_id": "SEQ02",
                        "camera_profile": "restrained",
                        "lighting_profile": "cinematic",
                    }
                ],
            },
        ],
    }
    (run_dir / "variant-plan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SequenceVariantPlan.model_validate(payload)


def _assemble(
    run_dir: Path,
    backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    base_report = render_sequence_quality(
        run_dir,
        quality="final",
        backend=backend,
    )
    backend.jobs.clear()
    qa_calls: list[tuple[str, list[str]]] = []

    def passed_qa(*_args, **kwargs):
        report = kwargs.get("render_report") or _args[4]
        qa_calls.append((report.final_file, [item.sequence_id for item in report.sequences]))
        return SimpleNamespace(status="passed")

    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        passed_qa,
    )
    production = load_production_plan(run_dir / "production-plan.json")
    local = load_local_sequence_plan(run_dir / "local-sequence-plan.json")
    online = load_online_plan(run_dir / "online-plan.json")
    manifest = assemble_sequence_variants(
        run_dir,
        production,
        local,
        online,
        _variant_plan(run_dir),
        base_report,
        output_root=run_dir,
        backend=backend,
    )
    return manifest, qa_calls


def test_background_music_is_applied_to_master_and_every_variant(v2_run, fake_sequence_backend, monkeypatch):
    calls = []
    monkeypatch.setattr('video_harness.music.score_master',
                        lambda *args, **kwargs: calls.append(kwargs['source'].name), raising=False)
    _assemble(v2_run, fake_sequence_backend, monkeypatch)
    # Base final plus each of the four final variant masters.
    assert calls == ['final.mp4'] * 5


def _variant_workspace(run_dir: Path, variant_id: str) -> Path:
    matches = list(
        (run_dir / ".sequence-variants").glob(
            f".transaction-*/workspaces/{variant_id}"
        )
    )
    assert len(matches) == 1
    return matches[0]


def test_sequence_variants_reuse_unmodified_sequence_masters(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, qa_calls = _assemble(v2_run, fake_sequence_backend, monkeypatch)

    assert manifest.variants[1].rendered_sequence_ids == ["SEQ02"]
    assert manifest.variants[1].reused_sequence_ids == ["SEQ01"]
    assert [job["sequence_id"] for job in fake_sequence_backend.jobs] == [
        "SEQ02",
        "SEQ02",
        "SEQ02",
    ]
    assert len(qa_calls) == 4
    assert all(ids == ["SEQ01", "SEQ02"] for _, ids in qa_calls)
    workspace = _variant_workspace(v2_run, "explain")
    reused_report = v2_run / "videoFiles/sequences/final/SEQ01-frame-report.json"
    frame_paths = json.loads(reused_report.read_text(encoding="utf-8"))["frames"]
    assert frame_paths
    assert all((v2_run / relative).is_file() for relative in frame_paths)
    assert not (
        workspace / "videoFiles/sequences/final/SEQ01-frame-report.json"
    ).exists()


def test_no_copy_of_reused_sequence_artifacts_before_variant_concat(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    """Copying a reused master, cache, report, scene slice, or frame is a regression."""
    args = _runtime_args(v2_run, fake_sequence_backend)
    base_root = args[5].artifact_root.resolve()
    seq01 = args[5].sequences[0]
    frame_files = json.loads(
        (base_root / seq01.state_report_file).read_text(encoding="utf-8")
    )["frames"]
    protected_sources = {
        (base_root / relative).resolve()
        for relative in (
            seq01.master_file,
            seq01.narrated_file,
            seq01.state_report_file,
            seq01.state_cache_file,
            *frame_files,
            *(
                relative
                for scene_slice in seq01.scene_slices
                for relative in (scene_slice.silent_file, scene_slice.narrated_file)
            ),
        )
    }
    original_copy2 = shutil.copy2

    def reject_reused_copy(source, destination, *copy_args, **copy_kwargs):
        if Path(source).resolve() in protected_sources:
            raise AssertionError(f"reused artifact was copied: {source}")
        return original_copy2(source, destination, *copy_args, **copy_kwargs)

    narrated_concat_inputs: list[list[Path]] = []
    narrated_concat_options: list[tuple[float, float, float]] = []
    concat_performance: list[tuple[object, dict[str, object]]] = []
    original_concat = sequence_render_module.concat_videos

    def record_concat(inputs, destination, *, require_audio, **kwargs):
        paths = list(inputs)
        concat_performance.append(
            (kwargs.get("performance"), kwargs.get("performance_labels", {}))
        )
        if require_audio:
            narrated_concat_inputs.append(paths)
            narrated_concat_options.append(
                (
                    kwargs.get("transition_seconds", 0.0),
                    kwargs.get("transition_fade_seconds", 0.0),
                    kwargs["expected_duration"],
                )
            )
        return original_concat(paths, destination, require_audio=require_audio, **kwargs)

    monkeypatch.setattr("video_harness.sequence_variants.shutil.copy2", reject_reused_copy)
    monkeypatch.setattr(
        "video_harness.sequence_variants.sequence_render_module.concat_videos",
        record_concat,
    )
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )
    recorder = PerformanceRecorder()

    manifest = assemble_sequence_variants(
        *args,
        output_root=v2_run,
        backend=fake_sequence_backend,
        performance=recorder,
    )

    workspace = _variant_workspace(v2_run, "explain")
    assert [job["sequence_id"] for job in fake_sequence_backend.jobs] == [
        "SEQ02",
        "SEQ02",
        "SEQ02",
    ]
    assert manifest.variants[1].reused_sequence_ids == ["SEQ01"]
    assert narrated_concat_inputs == []
    assert narrated_concat_options == []
    final_mux = next(item for item in fake_sequence_backend.muxes if item[2] == workspace / "final.mp4")
    assert final_mux[0] == workspace / "video-only.mp4"
    assert [item[1] for item in final_mux[1]] == [0, 188, 308]

    def copied_artifact_metrics(result) -> tuple[int, int]:
        relatives = [
            result.master_file,
            result.narrated_file,
            result.state_report_file,
            result.state_cache_file,
            *(
                relative
                for scene_slice in result.scene_slices
                for relative in (scene_slice.silent_file, scene_slice.narrated_file)
            ),
            *[
                f".render-cache/sequences/final/{result.sequence_id}/frame-{frame:06d}.png"
                for frame in range(result.frame_count)
            ],
        ]
        paths = [base_root / relative for relative in relatives]
        return len(paths), sum(path.stat().st_size for path in paths)

    seq01_metrics = copied_artifact_metrics(seq01)
    seq02_metrics = copied_artifact_metrics(args[5].sequences[1])
    report = recorder.report()
    assert report.avoided_copy_files == 4 * seq01_metrics[0] + seq02_metrics[0]
    assert report.avoided_copy_bytes == 4 * seq01_metrics[1] + seq02_metrics[1]
    assert report.rendered_frame_count == 3 * args[5].sequences[1].frame_count
    assert report.reused_frame_count == (
        4 * seq01.frame_count + args[5].sequences[1].frame_count
    )
    assert set(report.output_frame_counts) == {
        "variant:balanced",
        "variant:explain",
        "variant:dynamic",
        "variant:cinematic",
    }
    balanced_counts = report.output_frame_counts["variant:balanced"]
    assert balanced_counts.rendered_frame_count == 0
    assert balanced_counts.reused_frame_count == (
        seq01.frame_count + args[5].sequences[1].frame_count
    )
    assert balanced_counts.reused_sequence_ids == ["SEQ01", "SEQ02"]
    for variant_id in ("explain", "dynamic", "cinematic"):
        counts = report.output_frame_counts[f"variant:{variant_id}"]
        assert counts.rendered_frame_count == args[5].sequences[1].frame_count
        assert counts.reused_frame_count == seq01.frame_count
        assert counts.rendered_sequence_ids == ["SEQ02"]
        assert counts.reused_sequence_ids == ["SEQ01"]
    assert [
        (
            labels["variant_id"],
            labels["output_kind"],
            attached_recorder is recorder,
        )
        for attached_recorder, labels in concat_performance
    ] == [
        (variant_id, output_kind, True)
        for variant_id in ("balanced", "explain", "dynamic", "cinematic")
        for output_kind in ("silent",)
    ]


def test_sequence_variant_manifest_writes_four_named_edits_and_hashes(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest, _ = _assemble(v2_run, fake_sequence_backend, monkeypatch)

    assert [item.final_file for item in manifest.variants] == [
        "final.mp4",
        "videoFiles/variants/02_explain.mp4",
        "videoFiles/variants/03_dynamic.mp4",
        "videoFiles/variants/04_cinematic.mp4",
    ]
    assert [item.original_file for item in manifest.variants] == [
        "video-only.mp4",
        "videoFiles/variants/video-only/02_explain.mp4",
        "videoFiles/variants/video-only/03_dynamic.mp4",
        "videoFiles/variants/video-only/04_cinematic.mp4",
    ]
    assert manifest.state_cache_sha256 == {
        result.sequence_id: script_sha256(
            manifest_path(v2_run, result.state_cache_file)
        )
        for result in render_sequence_quality(
            v2_run, quality="final", backend=fake_sequence_backend
        ).sequences
    }
    assert (v2_run / "videoFiles/variants/variants.json").is_file()
    assert all(item.qa_status == "passed" for item in manifest.variants)
    for output in manifest.variants:
        workspace = _variant_workspace(v2_run, output.variant_id)
        for sequence_id, expected_hash in manifest.state_cache_sha256.items():
            root = workspace if sequence_id in output.rendered_sequence_ids else v2_run
            cache = root / f"videoFiles/sequences/state-cache/{sequence_id}.json"
            assert script_sha256(cache) == expected_hash


def test_balanced_only_variant_assembly_materializes_only_balanced_edit(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    base_report = render_sequence_quality(
        v2_run, quality="final", backend=fake_sequence_backend
    )
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )

    manifest = assemble_sequence_variants(
        v2_run,
        load_production_plan(v2_run / "production-plan.json"),
        load_local_sequence_plan(v2_run / "local-sequence-plan.json"),
        load_online_plan(v2_run / "online-plan.json"),
        _variant_plan(v2_run),
        base_report,
        output_root=v2_run,
        backend=fake_sequence_backend,
        variant_mode="balanced_only",
        settings=HarnessSettings(),
    )

    assert [item.variant_id for item in manifest.variants] == ["balanced"]
    assert (v2_run / "final.mp4").is_file()
    assert not (v2_run / "videoFiles/variants/02_explain.mp4").exists()


def manifest_path(root: Path, relative: str) -> Path:
    return root / relative


def test_rerender_rejects_mutated_base_canonical_timeline(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    base_report = render_sequence_quality(
        v2_run,
        quality="final",
        backend=fake_sequence_backend,
    )
    cache_path = v2_run / base_report.sequences[1].state_cache_file
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload[0]["simulation_time"] += 1
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )

    with pytest.raises(ValueError, match="canonical frame/simulation-time table"):
        assemble_sequence_variants(
            v2_run,
            load_production_plan(v2_run / "production-plan.json"),
            load_local_sequence_plan(v2_run / "local-sequence-plan.json"),
            load_online_plan(v2_run / "online-plan.json"),
            _variant_plan(v2_run),
            base_report,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )


def _runtime_args(run_dir: Path, backend: FakeSequenceBackend):
    base_report = render_sequence_quality(run_dir, quality="final", backend=backend)
    backend.jobs.clear()
    return (
        run_dir,
        load_production_plan(run_dir / "production-plan.json"),
        load_local_sequence_plan(run_dir / "local-sequence-plan.json"),
        load_online_plan(run_dir / "online-plan.json"),
        _variant_plan(run_dir),
        base_report,
    )


def _public_variant_paths(run_dir: Path) -> list[Path]:
    return [
        run_dir / "final.mp4",
        run_dir / "video-only.mp4",
        run_dir / "videoFiles/variants/02_explain.mp4",
        run_dir / "videoFiles/variants/03_dynamic.mp4",
        run_dir / "videoFiles/variants/04_cinematic.mp4",
        run_dir / "videoFiles/variants/video-only/02_explain.mp4",
        run_dir / "videoFiles/variants/video-only/03_dynamic.mp4",
        run_dir / "videoFiles/variants/video-only/04_cinematic.mp4",
        run_dir / "videoFiles/variants/variants.json",
    ]


def _seed_public_variant_set(run_dir: Path) -> dict[Path, bytes]:
    prior: dict[Path, bytes] = {}
    for index, path in enumerate(_public_variant_paths(run_dir)):
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"previous-{index}".encode()
        path.write_bytes(content)
        prior[path] = content
    return prior


def test_every_isolated_workspace_passes_real_v2v_reference_coverage(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    coverage: list[tuple[Path, list[str]]] = []

    def reference_qa(*_args, **kwargs):
        report = kwargs.get("render_report") or _args[4]
        issues = validate_reference_coverage(
            args[3], report.artifact_root, quality="final"
        )
        coverage.append((report.artifact_root, [issue.code for issue in issues]))
        return SimpleNamespace(status="failed" if issues else "passed")

    monkeypatch.setattr("video_harness.sequence_variants.run_sequence_qa", reference_qa)

    assemble_sequence_variants(
        *args,
        output_root=v2_run,
        backend=fake_sequence_backend,
    )

    assert len(coverage) == 4
    assert all(issue_codes == [] for _, issue_codes in coverage)
    assert all(
        (workspace / shot.reference_video_file).is_file()
        for workspace, _ in coverage
        for shot in args[3].shots
        if shot.preferred_mode == "v2v" and shot.reference_video_file is not None
    )


@pytest.mark.parametrize("failed_recipe", ["balanced", "explain", "dynamic", "cinematic"])
def test_any_variant_qa_failure_preserves_the_complete_public_set(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
    failed_recipe: str,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    prior = _seed_public_variant_set(v2_run)
    calls = iter(("balanced", "explain", "dynamic", "cinematic"))

    def selective_qa(*_args, **_kwargs):
        recipe = next(calls)
        return SimpleNamespace(status="failed" if recipe == failed_recipe else "passed")

    monkeypatch.setattr("video_harness.sequence_variants.run_sequence_qa", selective_qa)

    with pytest.raises(ValueError, match=rf"variant {failed_recipe} failed"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert {path: path.read_bytes() for path in prior} == prior


def test_publication_failure_rolls_back_the_complete_public_set(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    prior = _seed_public_variant_set(v2_run)
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )
    original_replace = Path.replace
    failed = False

    def fail_once(source: Path, target: Path):
        nonlocal failed
        if not failed and Path(target).name == "03_dynamic.mp4":
            failed = True
            raise OSError("injected publication failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_once)

    with pytest.raises(OSError, match="injected publication failure"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert {path: path.read_bytes() for path in prior} == prior


@pytest.mark.parametrize(
    "mutation",
    ["in_memory_replacement", "in_memory_nested", "workspace_file", "base_file"],
)
def test_rerender_rejects_every_canonical_cache_mutation_channel(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    original_render = fake_sequence_backend.render_frames
    base_cache = v2_run / args[5].sequences[1].state_cache_file

    def malicious_render(job, cache_dir):
        if mutation == "in_memory_replacement":
            job["canonical_state_cache"] = copy.deepcopy(job["canonical_state_cache"])
        elif mutation == "in_memory_nested":
            job["canonical_state_cache"][0]["simulation_time"] += 999
        elif mutation == "workspace_file":
            path = (
                cache_dir.parents[2]
                / "videoFiles/sequences/state-cache"
                / f"{job['sequence_id']}.json"
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload[0]["simulation_time"] += 999
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "base_file":
            payload = json.loads(base_cache.read_text(encoding="utf-8"))
            payload[0]["simulation_time"] += 999
            base_cache.write_text(json.dumps(payload), encoding="utf-8")
        return original_render(job, cache_dir)

    fake_sequence_backend.render_frames = malicious_render
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )

    with pytest.raises(ValueError, match="canonical cache"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )


@pytest.mark.parametrize("artifact", ["production", "local", "online", "variant"])
def test_assembler_rejects_in_memory_plan_divergence_before_variant_work(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    artifact: str,
):
    args = list(_runtime_args(v2_run, fake_sequence_backend))
    if artifact == "production":
        args[1].defaults.width += 1
    elif artifact == "local":
        args[2].defaults.width += 1
    elif artifact == "online":
        args[3].shots[0].primary_event = "changed in memory"
    else:
        args[4].variants[1].overrides[0].lighting_profile = "cinematic"

    with pytest.raises(ValueError, match=rf"{artifact}.*on-disk artifact"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert fake_sequence_backend.jobs == []


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "alias_kind",
    ["root_final", "variant_media", "variant_manifest", "variants_parent"],
)
def test_public_destination_alias_is_rejected_before_publication(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    variants_directory = v2_run / "videoFiles/variants"
    if alias_kind == "root_final":
        alias = v2_run / "final.mp4"
        target = v2_run / "script.json"
        alias.unlink()
    elif alias_kind == "variant_media":
        variants_directory.mkdir(parents=True)
        alias = variants_directory / "02_explain.mp4"
        target = v2_run / args[5].sequences[0].master_file
    elif alias_kind == "variant_manifest":
        variants_directory.mkdir(parents=True)
        alias = variants_directory / "variants.json"
        target = v2_run / "variant-plan.json"
    else:
        alias = variants_directory
        target = v2_run / "videoFiles/original"
    alias.symlink_to(target, target_is_directory=alias_kind == "variants_parent")
    before = _file_bytes(v2_run)
    publication_moves: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def observe_replace(source: Path, destination: Path):
        source_path = Path(source).absolute()
        destination_path = Path(destination).absolute()
        if "publication-stage" in source_path.parts:
            publication_stage = next(
                parent
                for parent in source_path.parents
                if parent.name == "publication-stage"
            )
            if not destination_path.is_relative_to(publication_stage):
                publication_moves.append((source_path, destination_path))
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", observe_replace)
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )

    with pytest.raises(ValueError, match="symlink"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert publication_moves == []
    assert alias.is_symlink()
    assert {
        relative: (v2_run / relative).read_bytes() for relative in before
    } == before


def test_internal_workspace_symlink_cannot_delete_video_artifacts(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    marker = v2_run / "videoFiles/keep-existing.txt"
    marker.write_bytes(b"keep-existing")
    transaction_root = v2_run / ".sequence-variants"
    transaction_root.mkdir()
    alias = transaction_root / "balanced"
    alias.symlink_to(v2_run / "videoFiles", target_is_directory=True)
    before = _file_bytes(v2_run / "videoFiles")

    with pytest.raises(ValueError, match="symlink"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert alias.is_symlink()
    assert _file_bytes(v2_run / "videoFiles") == before
    assert fake_sequence_backend.jobs == []


def test_external_transaction_root_symlink_is_rejected_without_external_writes(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    tmp_path: Path,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "keep-existing.txt"
    marker.write_bytes(b"keep-existing")
    (v2_run / ".sequence-variants").symlink_to(
        external, target_is_directory=True
    )
    before = _file_bytes(external)

    with pytest.raises(ValueError, match="symlink"):
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert _file_bytes(external) == before
    assert fake_sequence_backend.jobs == []


@pytest.mark.parametrize(
    "mutation",
    ["in_memory_replacement", "in_memory_nested", "workspace_file", "base_file"],
)
def test_backend_mutation_then_raise_restores_every_canonical_cache_channel(
    v2_run: Path,
    fake_sequence_backend: FakeSequenceBackend,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
):
    args = _runtime_args(v2_run, fake_sequence_backend)
    base_cache = v2_run / args[5].sequences[1].state_cache_file
    expected_bytes = base_cache.read_bytes()

    def malicious_render(job, cache_dir):
        if mutation == "in_memory_replacement":
            job["canonical_state_cache"] = copy.deepcopy(job["canonical_state_cache"])
        elif mutation == "in_memory_nested":
            job["canonical_state_cache"][0]["simulation_time"] += 999
        elif mutation == "workspace_file":
            path = (
                cache_dir.parents[2]
                / "videoFiles/sequences/state-cache"
                / f"{job['sequence_id']}.json"
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload[0]["simulation_time"] += 999
            path.write_text(json.dumps(payload), encoding="utf-8")
        elif mutation == "base_file":
            payload = json.loads(base_cache.read_text(encoding="utf-8"))
            payload[0]["simulation_time"] += 999
            base_cache.write_text(json.dumps(payload), encoding="utf-8")
        raise RuntimeError("backend exploded after mutation")

    fake_sequence_backend.render_frames = malicious_render
    monkeypatch.setattr(
        "video_harness.sequence_variants.run_sequence_qa",
        lambda *_args, **_kwargs: SimpleNamespace(status="passed"),
    )

    with pytest.raises(ValueError, match="canonical cache") as caught:
        assemble_sequence_variants(
            *args,
            output_root=v2_run,
            backend=fake_sequence_backend,
        )

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "backend exploded" in str(caught.value.__cause__)
    assert base_cache.read_bytes() == expected_bytes
    workspace_cache = (
        _variant_workspace(v2_run, "explain")
        / "videoFiles/sequences/state-cache/SEQ02.json"
    )
    assert workspace_cache.read_bytes() == expected_bytes


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """Synthetic variant fixtures isolate cache/transaction behavior.
    Real approval and continuity failures are tested in test_creative_gates.py.
    """
    monkeypatch.setattr('video_harness.creative_gates.require_creative_plan', lambda *args, **kwargs: None)
    monkeypatch.setattr('video_harness.creative_gates.render_report_continuity_issues', lambda *args, **kwargs: [])
    monkeypatch.setattr('video_harness.video_plan_approval.require_current_video_plan_approval', lambda *args, **kwargs: None)
