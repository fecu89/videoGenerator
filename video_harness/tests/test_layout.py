from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
ALLOWED_ROOT_ENTRIES = {
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "requirements.txt",
    "runs",
    "settings.md",
    "settings.json",
    "video_harness",
}


def test_project_root_contains_required_public_entries():
    assert ALLOWED_ROOT_ENTRIES <= {path.name for path in PROJECT_DIR.iterdir()}


def test_render_performance_operator_document_is_part_of_the_harness_layout():
    assert (PROJECT_DIR / "video_harness/docs/render-performance.md").is_file()
