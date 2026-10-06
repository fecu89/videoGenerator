from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_video_prompt_is_an_ordered_entry_point_for_three_specialized_planners():
    text = read("agent/prompts/video.md")
    names = ("video-router.md", "video-local.md", "video-generated.md")
    positions = [text.index(name) for name in names]
    assert positions == sorted(positions)
    assert text.count("처음부터 끝까지") >= 3


def test_router_prompt_owns_common_schema_v2_sequences_beats_and_routes():
    text = read("agent/prompts/video-router.md")
    for phrase in (
        "schema_version",
        "visual_sequences",
        "visual_beats",
        "primary_route",
        "relationship_owner",
        "[start_frame, end_frame)",
        "online_required",
    ):
        assert phrase in text


def test_local_prompt_owns_canonical_frames_controllers_and_persistent_state():
    text = read("agent/prompts/video-local.md")
    for phrase in (
        "scene_spans",
        "tail_silence_frames",
        "patch_targets",
        "priority",
        "controller",
        "simulation_time_start",
        "simulation_time_end",
        "나레이션 씬 경계는 오디오와 검토 슬라이스의 마커일 뿐이다. 같은 visual_sequence 안에서는 장면 그래프, 시뮬레이션 시간, 카메라 상태, 누적 레이어를 초기화하지 않는다.",
    ):
        assert phrase in text


def test_generated_prompt_preserves_every_beat_and_v2v_science_default():
    text = read("agent/prompts/video-generated.md")
    for phrase in (
        "4~8초",
        "T2V",
        "I2V",
        "first-last",
        "V2V",
        "science_authority: local_reference",
        "videoFiles/prompts/online/",
        "모든 visual_beat를 online_shot으로 덮는다. 로컬이 기본 경로인 비트도 온라인 대체 프롬프트와 메타데이터를 생략하지 않는다.",
    ):
        assert phrase in text


def test_workflow_uses_plan_compile_and_one_stop_local_flow():
    text = read("agent/WORKFLOW.md")
    for phrase in (
        "production-plan.json",
        "local-sequence-plan.json",
        "online-plan.json",
        "python -m video_harness plan-video",
        "python -m video_harness produce runs/<run>",
        "python -m video_harness validate runs/<run>",
        "videoFiles/",
        "render.preview_interval_seconds",
        "호환 명령",
        "variant-plan.json",
        "videoFiles/variants/02_explain.mp4",
        "schema-v1 호환 실행에서만 사용",
    ):
        assert phrase in text


def test_workflow_requires_human_script_approval_and_keeps_settings_duration_gate():
    text = read("agent/WORKFLOW.md")
    assert "사람의 피드백" in text
    assert "명시적으로 승인" in text
    assert "침묵" in text
    assert "별도의 승인 메시지 없이 음성부터 최종 합본까지 계속 진행" not in text
    assert "voice.min_scene_seconds" in text
    assert "voice.max_scene_seconds" in text
    assert "유효하지 않은 음성이 하나라도 있으면" in text


def test_agent_documents_resolve_effective_settings_before_production():
    workflow = read("agent/WORKFLOW.md")
    video_prompt = read("agent/prompts/video.md")
    story_prompt = read("agent/prompts/story.md")

    assert "python -m video_harness settings [run]" in workflow
    assert "python -m video_harness produce runs/<run>" in workflow
    assert "effective settings" in video_prompt
    assert "effective settings" in story_prompt


def test_agent_bootstrap_requires_settings_before_workflow():
    bootstrap = (ROOT.parent / "AGENTS.md").read_text(encoding="utf-8")

    assert "settings.md" in bootstrap
    assert bootstrap.index("settings.md") < bootstrap.index("WORKFLOW.md")


def test_render_performance_documents_explain_the_safety_and_qa_gates():
    """Catch a missing operator contract for a performance-only change."""
    documents = "\n".join(
        read(relative)
        for relative in (
            "docs/render-performance.md",
            "agent/WORKFLOW.md",
            "../README.md",
            "../settings.md",
        )
    )
    for phrase in (
        "render-performance.json",
        "benchmark-render",
        "backend.actual",
        "same-backend exact determinism",
        "SSIM/PSNR",
        "concat normalization fallback",
    ):
        assert phrase in documents


def test_direction_and_prompts_replace_slide_layout_with_keyword_callouts():
    direction = read("agent/DIRECTION.md")
    for banned in ("발표 슬라이드처럼", "왼쪽 이미지 · 오른쪽 설명", "size=1.30"):
        assert banned not in direction
    for phrase in ("객체가 주인공", "labels", "비트당", "8자", "지시선", "anchor"):
        assert phrase in direction
    for relative in ("agent/prompts/video-local.md", "agent/prompts/video-router.md", "agent/prompts/video.md", "agent/prompts/video-generated.md"):
        text = read(relative)
        assert "labels" in text, relative
        assert "오른쪽 설명" not in text, relative
    local = read("agent/prompts/video-local.md")
    marker = local.index("새 스키마 필드")
    assert "labels" in local[marker - 400:marker]


def test_workflow_documents_preview_draft_final_approvals():
    combined = read("../AGENTS.md") + read("agent/WORKFLOW.md")
    for phrase in ("python -m video_harness preview", "프리뷰승인", "approve-preview", "초본승인", "approve-draft"):
        assert phrase in combined
    assert combined.index("preview runs/<run>") < combined.index("produce runs/<run> --quality draft")
    assert combined.index("approve-draft") < combined.index("produce runs/<run> --quality final")


def test_review_template_and_gate_docs_mention_callout_checks():
    template = read("agent/templates/visual-review.md")
    assert "라벨 수" in template and "지시선" in template
    gates = read("docs/creative-gates.md")
    assert "text-plan-gate.json" in gates and "label_clipped" in gates
    assert "읽기 쉬운 글자, 모든 중간 프레임의 미학까지 자동 판정하는 검사는 아니다" not in gates


def test_direction_and_prompts_put_all_text_into_subtitles():
    direction = read("agent/DIRECTION.md")
    for phrase in ("글자는 자막으로", "화면 안 글자", "subtitles", "keywords"):
        assert phrase in direction
    assert direction.index("## 3.") < direction.index("### 기본 화면 크기")
    for relative in ("agent/prompts/video-local.md", "agent/prompts/video-router.md", "agent/prompts/video.md", "agent/prompts/video-generated.md"):
        assert "화면 글자 없음" in read(relative), relative


def test_workflow_documents_translation_and_language_voice_steps():
    combined = read("../AGENTS.md") + read("agent/WORKFLOW.md")
    for phrase in ("translate-scaffold", "--target-language all", "final-en.mp4", "final-ko.mp4", "translations.json", "language-voices.json"):
        assert phrase in combined
    assert combined.index("translate-scaffold") < combined.index("--target-language all") < combined.index("plan-video runs/<run>")


def test_review_template_and_gate_docs_cover_subtitles():
    template = read("agent/templates/visual-review.md")
    assert template.index("자막 외 화면 글자 없음") < template.index("해결이 다음 질문으로")
    gates = read("docs/creative-gates.md")
    for phrase in ("translation-gate.json", "translation-fit-gate-<lang>.json", "subtitle-gate-<lang>.json", "localization-final-gate.json", "on_screen_text_found", "callouts_forbidden"):
        assert phrase in gates
    architecture = read("docs/architecture.md")
    for name in ("kokoro_voice.py", "localize_voice.py", "translations.py", "subtitles.py", "localize.py", "language_voices.py"):
        assert name in architecture
