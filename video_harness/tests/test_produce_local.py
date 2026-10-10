from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness.produce_local import (
    _derive_owned_public_manifest,
    final_staging_directory,
    load_local_production_context,
    produce_local,
    publish_staged_outputs,
)
from video_harness.performance import PerformanceRecorder
from video_harness.settings import HarnessSettings


PROTECTED = (
    "video-plan.md",
    "final-draft.mp4",
    "video-only-draft.mp4",
    "final.mp4",
    "video-only.mp4",
    "videoFiles/prompts/local/SEQ01.md",
    "videoFiles/prompts/online/ON-B01.txt",
    "videoFiles/prompts/online/ON-B01.json",
    "videoFiles/variants/02_explain.mp4",
    "videoFiles/variants/video-only/02_explain.mp4",
    "videoFiles/variants/03_dynamic.mp4",
    "videoFiles/variants/video-only/03_dynamic.mp4",
    "videoFiles/variants/04_cinematic.mp4",
    "videoFiles/variants/video-only/04_cinematic.mp4",
    "videoFiles/variants/variants.json",
    "videoFiles/previews/half-second/SEQ01/000000ms.png",
    "videoFiles/previews/half-second/contact-sheet.png",
    "videoFiles/sequences/draft/qa-report.json",
    "videoFiles/sequences/draft/SEQ01.mp4",
    "videoFiles/sequences/draft/SEQ01-narrated.mp4",
    "videoFiles/sequences/draft/SEQ01-frame-report.json",
    "videoFiles/sequences/draft/SEQ01-render-record.json",
    "videoFiles/sequences/final/SEQ01.mp4",
    "videoFiles/sequences/final/SEQ01-narrated.mp4",
    "videoFiles/sequences/final/SEQ01-frame-report.json",
    "videoFiles/sequences/final/SEQ01-render-record.json",
    "videoFiles/sequences/state-cache/SEQ01.json",
    "videoFiles/draft/original/01_scene.mp4",
    "videoFiles/draft/01_scene.mp4",
    "videoFiles/original/01_scene.mp4",
    "videoFiles/01_scene.mp4",
    "videoFiles/onlineReferences/reference.mp4",
    "qa-report.json",
    "local-production-report.json",
)


def test_owned_manifest_includes_qa_preview_artifacts() -> None:
    preview = "videoFiles/previews/half-second/SEQ01/000500ms.png"
    contact_sheet = "videoFiles/previews/half-second/contact-sheet.png"
    context = SimpleNamespace(
        script=SimpleNamespace(scenes=[]),
        production=object(),
        local=SimpleNamespace(
            sequences=[SimpleNamespace(sequence_id="SEQ01", scene_spans=[])]
        ),
        online=SimpleNamespace(shots=[]),
        variant=object(),
    )
    draft_qa = SimpleNamespace(
        sequence_results=[
            SimpleNamespace(sequence_id="SEQ01", preview_files=[preview])
        ],
        contact_sheet_file=contact_sheet,
    )
    final_qa = SimpleNamespace(
        sequence_results=[
            SimpleNamespace(sequence_id="SEQ01", preview_files=[preview])
        ],
        contact_sheet_file=contact_sheet,
    )

    manifest = _derive_owned_public_manifest(
        context,
        draft_qa,
        final_qa,
        compile_prompts=False,
        create_references=False,
        variant_mode="balanced_only",
    )

    assert {preview, contact_sheet} <= manifest


def _seed_protected(run_dir: Path) -> dict[str, bytes]:
    seeded: dict[str, bytes] = {}
    for relative in PROTECTED:
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        value = f"known-good:{relative}".encode()
        path.write_bytes(value)
        seeded[relative] = value
    return seeded


def _assert_protected(run_dir: Path, expected: dict[str, bytes]) -> None:
    assert {relative: (run_dir / relative).read_bytes() for relative in expected} == expected


def _install_fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    run_dir: Path,
    *,
    draft_status: str = "passed",
    final_status: str = "passed",
    artifact_issues: list[object] | None = None,
    report_issues: list[object] | None = None,
) -> list[str]:
    import video_harness.produce_local as module

    events: list[str] = []
    context = SimpleNamespace(
        run_dir=run_dir,
        script=object(),
        production=object(),
        local=object(),
        online=object(),
        variant=object(),
    )

    def load_context(_run_dir: Path):
        events.append("validate")
        return context

    def compile_artifacts(output_root, *_args, **_kwargs):
        events.append("compile")
        root = Path(output_root)
        for relative in (
            "video-plan.md",
            "videoFiles/prompts/local/SEQ01.md",
            "videoFiles/prompts/online/ON-B01.txt",
            "videoFiles/prompts/online/ON-B01.json",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"new:{relative}".encode())
        return []

    def render(
        _run_dir: Path,
        *,
        quality: str,
        output_root=None,
        force=False,
        settings=None,
        performance=None,
    ):
        if performance is not None:
            events.append("performance-render")
        label = "final-staging" if quality == "final" else "draft"
        events.append(f"render:{label}")
        root = Path(output_root) if output_root is not None else run_dir
        final_name = "final.mp4" if quality == "final" else "final-draft.mp4"
        original_name = "video-only.mp4" if quality == "final" else "video-only-draft.mp4"
        (root / final_name).write_bytes(f"new-{quality}-final".encode())
        (root / original_name).write_bytes(f"new-{quality}-original".encode())
        for relative in (
            f"videoFiles/sequences/{quality}/SEQ01.mp4",
            f"videoFiles/sequences/{quality}/SEQ01-narrated.mp4",
            f"videoFiles/sequences/{quality}/SEQ01-frame-report.json",
            f"videoFiles/sequences/{quality}/SEQ01-render-record.json",
            "videoFiles/sequences/state-cache/SEQ01.json",
            f"videoFiles/{'draft/' if quality == 'draft' else ''}original/01_scene.mp4",
            f"videoFiles/{'draft/' if quality == 'draft' else ''}01_scene.mp4",
            "videoFiles/previews/half-second/SEQ01/000000ms.png",
            "videoFiles/previews/half-second/contact-sheet.png",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"new-{quality}:{relative}".encode())
        return SimpleNamespace(
            quality=quality,
            artifact_root=root,
            final_file=final_name,
            final_original_file=original_name,
            sequences=[],
        )

    def qa(*_args, quality: str, **_kwargs):
        if _kwargs.get("performance") is not None:
            events.append("performance-qa")
        events.append(f"qa:{quality}")
        status = draft_status if quality == "draft" else final_status
        report = _args[4]
        relative = (
            "videoFiles/sequences/draft/qa-report.json"
            if quality == "draft"
            else "qa-report.json"
        )
        path = Path(report.artifact_root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"new-{quality}-qa".encode())
        return SimpleNamespace(
            status=status,
            quality=quality,
            artifact_root=Path(report.artifact_root),
            contact_sheet_file="videoFiles/previews/half-second/contact-sheet.png",
            sequence_results=[
                SimpleNamespace(
                    sequence_id="SEQ01",
                    preview_files=[
                        "videoFiles/previews/half-second/SEQ01/000000ms.png"
                    ],
                )
            ],
        )

    def references(*_args, output_root: Path, **_kwargs):
        events.append("references")
        relative = "videoFiles/onlineReferences/reference.mp4"
        (Path(output_root) / relative).parent.mkdir(parents=True, exist_ok=True)
        (Path(output_root) / relative).write_bytes(b"reference")
        return [relative]

    def variants(*_args, output_root: Path, variant_mode: str = "four", **_kwargs):
        if _kwargs.get("performance") is not None:
            events.append("performance-variants")
        events.append("variants")
        outputs = []
        recipes = (
            ("balanced", "final.mp4", "video-only.mp4"),
            (
                "explain",
                "videoFiles/variants/02_explain.mp4",
                "videoFiles/variants/video-only/02_explain.mp4",
            ),
            (
                "dynamic",
                "videoFiles/variants/03_dynamic.mp4",
                "videoFiles/variants/video-only/03_dynamic.mp4",
            ),
            (
                "cinematic",
                "videoFiles/variants/04_cinematic.mp4",
                "videoFiles/variants/video-only/04_cinematic.mp4",
            ),
        )
        for variant_id, relative, original_relative in recipes:
            if variant_mode == "balanced_only" and variant_id != "balanced":
                continue
            for media_relative in (relative, original_relative):
                path = Path(output_root) / media_relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"new-{variant_id}:{media_relative}".encode())
            outputs.append(SimpleNamespace(variant_id=variant_id, final_file=relative))
        manifest = Path(output_root) / "videoFiles/variants/variants.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(b"new-variant-manifest")
        return SimpleNamespace(variants=outputs)

    real_publish = module.publish_staged_outputs

    def publish(run: Path, staging: Path, **kwargs):
        events.append("publish")
        return real_publish(run, staging, **kwargs)

    validation_results = [artifact_issues or [], report_issues or []]

    def validate(
        _run_dir: Path,
        *,
        require_local_report: bool = True,
        require_pipeline_report: bool = True,
        settings=None,
    ):
        assert require_pipeline_report is False
        events.append("validate-report" if require_local_report else "validate-artifacts")
        return validation_results.pop(0)

    def write_report(*_args, **_kwargs):
        events.append("write-report")
        (run_dir / "local-production-report.json").write_text(
            json.dumps({"status": "complete"}), encoding="utf-8"
        )
        variants = _args[3] if len(_args) > 3 else _kwargs.get("variants")
        return SimpleNamespace(
            status="complete",
            variant_files=[item.final_file for item in variants.variants],
        )

    monkeypatch.setattr(module, "load_local_production_context", load_context)
    monkeypatch.setattr(
        module,
        "resolve_run_settings",
        lambda _run_dir: HarnessSettings(),
    )
    monkeypatch.setattr(module, "write_compiled_artifacts", compile_artifacts)
    monkeypatch.setattr(module, "render_sequence_quality", render)
    monkeypatch.setattr(module, "run_sequence_qa", qa)
    monkeypatch.setattr(module, "create_online_references", references)
    monkeypatch.setattr(module, "assemble_sequence_variants", variants)
    monkeypatch.setattr(module, "publish_staged_outputs", publish)
    monkeypatch.setattr(module, "validate_run", validate)
    monkeypatch.setattr(module, "write_local_production_report", write_report)
    monkeypatch.setattr(
        module,
        "_derive_owned_public_manifest",
        lambda _context, _draft_qa, final_qa, **_kwargs: {
            relative
            for relative, _ in module._staged_manifest(final_qa.artifact_root)
            if not module._is_documented_internal(relative)
        },
    )
    monkeypatch.setattr(module, "_current_owned_public_files", lambda _run: set())
    monkeypatch.setattr(
        module,
        "_current_obsolete_owned_directories",
        lambda _run, _context: set(),
    )
    return events


def test_default_runs_only_draft_render_and_qa(monkeypatch, tmp_path):
    import video_harness.produce_local as module

    events = _install_fake_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "write_local_production_report", lambda *args, **kwargs: args[1])

    report = produce_local(tmp_path)

    assert report.quality == "draft"
    assert events == ["validate", "compile", "render:draft", "qa:draft"]
    assert (tmp_path / "final-draft.mp4").exists()
    assert not (tmp_path / "final.mp4").exists()


def test_final_runs_fixed_pipeline_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = _install_fake_pipeline(monkeypatch, run_dir)

    report = produce_local(run_dir, quality="final")

    assert events == [
        "validate",
        "compile",
        "render:draft",
        "qa:draft",
        "render:final-staging",
        "references",
        "qa:final",
        "variants",
        "publish",
        "validate-artifacts",
        "write-report",
        "validate-report",
    ]
    assert report.status == "complete"


def test_owned_manifest_includes_every_preview_declared_by_qa():
    """A successful QA report must be publishable with its own preview evidence."""
    preview = "videoFiles/previews/half-second/SEQ01/000000ms.png"
    contact_sheet = "videoFiles/previews/half-second/contact-sheet.png"
    context = SimpleNamespace(
        local=SimpleNamespace(
            sequences=[SimpleNamespace(sequence_id="SEQ01", scene_spans=[])]
        ),
        script=SimpleNamespace(scenes=[]),
    )
    qa = SimpleNamespace(
        sequence_results=[
            SimpleNamespace(sequence_id="SEQ01", preview_files=[preview])
        ],
        contact_sheet_file=contact_sheet,
    )

    owned = _derive_owned_public_manifest(
        context,
        qa,
        qa,
        compile_prompts=False,
        create_references=False,
        variant_mode="balanced_only",
    )

    assert {preview, contact_sheet} <= owned


def test_final_production_threads_one_recorder_through_render_qa_and_variants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Dropping a stage recorder must not make that stage disappear from diagnostics."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = _install_fake_pipeline(monkeypatch, run_dir)

    recorder = PerformanceRecorder()
    produce_local(run_dir, quality="final", performance=recorder)

    assert events.count("performance-render") == 2
    assert events.count("performance-qa") == 2
    assert events.count("performance-variants") == 1
    assert set(recorder.report().output_totals_ms) == {"base:draft", "base:final"}


def test_video_only_writes_no_prompt_or_reference_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    events = _install_fake_pipeline(monkeypatch, run_dir)

    produce_local(
        run_dir,
        quality="final",
        settings=HarnessSettings(pipeline={"output_mode": "video_only"}),
    )

    assert "compile" not in events
    assert "references" not in events
    assert not (run_dir / "videoFiles/prompts").exists()
    assert not (run_dir / "videoFiles/onlineReferences").exists()
    assert (run_dir / "final.mp4").is_file()


def test_video_only_preserves_reviewed_video_plan_and_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    reviewed = {
        "video-plan.md": b"reviewed visual script\n",
        "video-plan-approval.json": b'{"approved":true}\n',
    }
    for relative, content in reviewed.items():
        (run_dir / relative).write_bytes(content)
    _install_fake_pipeline(monkeypatch, run_dir)

    def reviewed_manifest(_context, _draft_qa, final_qa, **_kwargs):
        return {
            relative
            for relative, _ in module._staged_manifest(final_qa.artifact_root)
            if not module._is_documented_internal(relative)
        } | set(reviewed)

    monkeypatch.setattr(module, "_derive_owned_public_manifest", reviewed_manifest)
    monkeypatch.setattr(module, "_current_owned_public_files", lambda _run: set(reviewed))

    produce_local(
        run_dir,
        quality="final",
        settings=HarnessSettings(pipeline={"output_mode": "video_only"}),
    )

    assert {
        relative: (run_dir / relative).read_bytes()
        for relative in reviewed
    } == reviewed


def test_balanced_only_publishes_no_alternate_variant_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _install_fake_pipeline(monkeypatch, run_dir)

    report = produce_local(
        run_dir,
        quality="final",
        settings=HarnessSettings(pipeline={"variant_mode": "balanced_only"}),
    )

    assert report.variant_files == ["final.mp4"]
    assert not (run_dir / "videoFiles/variants/02_explain.mp4").exists()


def test_failed_draft_qa_stops_before_final_and_preserves_previous_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    previous = _seed_protected(run_dir)
    events = _install_fake_pipeline(monkeypatch, run_dir, draft_status="failed")

    with pytest.raises(ValueError, match="draft QA"):
        produce_local(run_dir, quality="final")

    assert events == ["validate", "compile", "render:draft", "qa:draft"]
    _assert_protected(run_dir, previous)


def test_final_mode_draft_render_and_qa_use_fresh_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _install_fake_pipeline(monkeypatch, run_dir)
    roots: list[tuple[str, Path]] = []
    original_render = module.render_sequence_quality
    original_qa = module.run_sequence_qa

    def record_render(path: Path, *, quality: str, output_root=None, **kwargs):
        roots.append((f"render:{quality}", Path(output_root or path)))
        return original_render(
            path, quality=quality, output_root=output_root, **kwargs
        )

    def record_qa(*args, quality: str, **kwargs):
        roots.append((f"qa:{quality}", Path(args[4].artifact_root)))
        return original_qa(*args, quality=quality, **kwargs)

    monkeypatch.setattr(module, "render_sequence_quality", record_render)
    monkeypatch.setattr(module, "run_sequence_qa", record_qa)

    produce_local(run_dir, quality="final")

    assert [label for label, _ in roots] == [
        "render:draft", "qa:draft", "render:final", "qa:final"
    ]
    assert len({root for _, root in roots}) == 1
    assert roots[0][1] != run_dir
    assert roots[0][1].parent == run_dir


def test_failed_final_qa_preserves_previous_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    previous = _seed_protected(run_dir)
    _install_fake_pipeline(monkeypatch, run_dir, final_status="failed")

    with pytest.raises(ValueError, match="final QA"):
        produce_local(run_dir, quality="final")

    _assert_protected(run_dir, previous)


def test_failed_variant_assembly_preserves_previous_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    previous = _seed_protected(run_dir)
    _install_fake_pipeline(monkeypatch, run_dir)

    def fail_variants(*_args, **_kwargs):
        raise ValueError("variant assembly failed")

    monkeypatch.setattr(module, "assemble_sequence_variants", fail_variants)
    with pytest.raises(ValueError, match="variant assembly"):
        produce_local(run_dir, quality="final")

    _assert_protected(run_dir, previous)


@pytest.mark.parametrize("failure_stage", ["artifact", "report"])
def test_post_publish_validation_failure_rolls_back_every_previous_public_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_stage: str
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    previous = _seed_protected(run_dir)
    issue = SimpleNamespace(code=f"{failure_stage}_failed")
    _install_fake_pipeline(
        monkeypatch,
        run_dir,
        artifact_issues=[issue] if failure_stage == "artifact" else None,
        report_issues=[issue] if failure_stage == "report" else None,
    )

    with pytest.raises(ValueError, match="validation failed"):
        produce_local(run_dir, quality="final")

    _assert_protected(run_dir, previous)
    retained = list(run_dir.glob('.local-final-*/final.mp4'))
    assert len(retained) == 1
    assert retained[0].is_file()


def test_publish_rejects_symlink_destination_without_changing_target(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    (run_dir / "final.mp4").symlink_to(outside)
    with final_staging_directory(run_dir) as staging:
        (staging / "final.mp4").write_bytes(b"new")

        with pytest.raises(ValueError, match="symlink"):
            publish_staged_outputs(run_dir, staging)

    assert outside.read_bytes() == b"outside"
    assert (run_dir / "final.mp4").is_symlink()


def test_failed_staging_preserves_expensive_render_for_recovery(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    with pytest.raises(ValueError, match='late validation'):
        with final_staging_directory(run_dir) as staging:
            (staging / 'final.mp4').write_bytes(b'rendered')
            raise ValueError('late validation')
    assert (staging / 'final.mp4').read_bytes() == b'rendered'


def test_successful_staging_is_cleaned(tmp_path):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    with final_staging_directory(run_dir) as staging:
        (staging / 'diagnostic.txt').write_text('done')
    assert not staging.exists()


def test_publish_rolls_back_earlier_replacements_when_a_later_replace_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final.mp4").write_bytes(b"old-final")
    (run_dir / "video-only.mp4").write_bytes(b"old-original")
    original_replace = module._replace_file
    calls = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replacement failure")
        original_replace(source, destination)

    monkeypatch.setattr(module, "_replace_file", fail_second)
    with final_staging_directory(run_dir) as staging:
        (staging / "final.mp4").write_bytes(b"new-final")
        (staging / "video-only.mp4").write_bytes(b"new-original")

        with pytest.raises(OSError, match="injected"):
            publish_staged_outputs(run_dir, staging)

    assert (run_dir / "final.mp4").read_bytes() == b"old-final"
    assert (run_dir / "video-only.mp4").read_bytes() == b"old-original"


def test_publish_requires_exact_staged_owned_manifest(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with final_staging_directory(run_dir) as staging:
        (staging / "final.mp4").write_bytes(b"new")
        (staging / "stale.mp4").write_bytes(b"stale")

        with pytest.raises(ValueError, match="staged artifact manifest"):
            publish_staged_outputs(
                run_dir,
                staging,
                expected_relatives={"final.mp4"},
                obsolete_relatives=set(),
            )

    assert not (run_dir / "final.mp4").exists()


def test_publish_transactionally_removes_obsolete_owned_artifacts(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / "videoFiles/sequences/final/STALE.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    with final_staging_directory(run_dir) as staging:
        (staging / "final.mp4").write_bytes(b"new")
        publish_staged_outputs(
            run_dir,
            staging,
            expected_relatives={"final.mp4"},
            obsolete_relatives={"videoFiles/sequences/final/STALE.mp4"},
        )

    assert not stale.exists()
    assert (run_dir / "final.mp4").read_bytes() == b"new"


def test_publish_transactionally_removes_obsolete_preview_directory(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / "videoFiles/previews/half-second/STALE"
    stale.mkdir(parents=True)
    with final_staging_directory(run_dir) as staging:
        (staging / "final.mp4").write_bytes(b"new")
        publish_staged_outputs(
            run_dir,
            staging,
            expected_relatives={"final.mp4"},
            obsolete_directories={"videoFiles/previews/half-second/STALE"},
        )

    assert not stale.exists()


def test_post_publish_failure_restores_obsolete_owned_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / "videoFiles/sequences/final/STALE.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"known-good-stale")
    issue = SimpleNamespace(code="artifact_failed")
    _install_fake_pipeline(monkeypatch, run_dir, artifact_issues=[issue])
    monkeypatch.setattr(
        module,
        "_current_owned_public_files",
        lambda _run: {"videoFiles/sequences/final/STALE.mp4"},
    )

    with pytest.raises(ValueError, match="validation failed"):
        produce_local(run_dir, quality="final")

    assert stale.read_bytes() == b"known-good-stale"


def test_post_publish_failure_restores_obsolete_empty_preview_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / "videoFiles/previews/half-second/STALE"
    stale.mkdir(parents=True)
    issue = SimpleNamespace(code="artifact_failed")
    _install_fake_pipeline(monkeypatch, run_dir, artifact_issues=[issue])
    monkeypatch.setattr(
        module,
        "_current_obsolete_owned_directories",
        lambda _run, _context: {"videoFiles/previews/half-second/STALE"},
    )

    with pytest.raises(ValueError, match="validation failed"):
        produce_local(run_dir, quality="final")

    assert stale.is_dir()


def test_context_rejects_symlink_run_before_writing_target(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        load_local_production_context(alias)

    assert list(target.iterdir()) == []


def test_context_rejects_symlink_in_run_parent_before_writing_target(tmp_path: Path):
    target_parent = tmp_path / "target-parent"
    run_dir = target_parent / "run"
    run_dir.mkdir(parents=True)
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(target_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        load_local_production_context(alias_parent / "run")

    assert list(run_dir.iterdir()) == []


def test_invalid_context_load_is_read_only(tmp_path: Path):
    run_dir = tmp_path / "invalid"
    run_dir.mkdir()
    (run_dir / "script.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        load_local_production_context(run_dir)

    assert {path.name for path in run_dir.iterdir()} == {"script.json"}


def test_semantically_invalid_context_load_is_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import video_harness.produce_local as module

    run_dir = tmp_path / "invalid-semantic"
    run_dir.mkdir()
    for name in (
        "script.json",
        "production-plan.json",
        "local-sequence-plan.json",
        "online-plan.json",
        "variant-plan.json",
    ):
        (run_dir / name).write_bytes(f"sentinel:{name}".encode())
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    issue = SimpleNamespace(code="semantic_failure")
    monkeypatch.setattr(
        module.ScriptArtifact,
        "model_validate_json",
        lambda _payload: object(),
    )
    monkeypatch.setattr(
        module, "load_production_plan", lambda _path: SimpleNamespace(schema_version=2)
    )
    monkeypatch.setattr(module, "load_local_sequence_plan", lambda _path: object())
    monkeypatch.setattr(module, "load_online_plan", lambda _path: object())
    monkeypatch.setattr(module, "SequenceVariantPlan", object)
    monkeypatch.setattr(module, "load_variant_plan", lambda _path: object())
    monkeypatch.setattr(module, "validate_plan_against_script", lambda *_args: [issue])
    monkeypatch.setattr(module, "validate_sequence_plans", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        module, "validate_sequence_variant_plan", lambda *_args, **_kwargs: []
    )

    with pytest.raises(ValueError, match="semantic_failure"):
        load_local_production_context(run_dir)

    assert {path.name: path.read_bytes() for path in run_dir.iterdir()} == before


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.video_plan_approval.require_current_video_plan_approval", lambda *args, **kwargs: [])
    monkeypatch.setattr("video_harness.creative_gates.require_rendered_continuity", lambda *args, **kwargs: [])


def test_produce_local_requires_stage_approval_for_keywords_runs(monkeypatch, tmp_path):
    import video_harness.produce_local as module
    import video_harness.video_plan_approval as approval
    monkeypatch.setattr(approval, "require_current_video_plan_approval", lambda _run: None)
    (tmp_path / "run-settings.json").write_text('{"schema_version": 4, "local_video": {"text_policy": "keywords"}}')
    with pytest.raises(ValueError, match="프리뷰승인"):
        module.produce_local(tmp_path, quality="draft", settings=HarnessSettings(local_video={"text_policy": "keywords"}))


def test_seed_approved_draft_does_not_publish_legacy_continuity_diagnostics(tmp_path):
    from video_harness.produce_local import _seed_approved_draft
    run, stage = tmp_path / 'run', tmp_path / 'stage'
    draft = run / 'videoFiles/sequences/draft'
    draft.mkdir(parents=True)
    (draft / 'SEQ01-continuity-refinement.json').write_text('{"diagnostic": true}')
    (draft / 'SEQ01-render-record.json').write_text('{"fingerprint": "reviewed"}')
    (draft / 'SEQ01.mp4').write_bytes(b'reviewed video')
    _seed_approved_draft(run, stage)
    copied = stage / 'videoFiles/sequences/draft'
    assert not (copied / 'SEQ01-continuity-refinement.json').exists()
    assert (copied / 'SEQ01-render-record.json').read_bytes() == (draft / 'SEQ01-render-record.json').read_bytes()
    assert (copied / 'SEQ01.mp4').read_bytes() == b'reviewed video'
    assert (draft / 'SEQ01-continuity-refinement.json').exists()
