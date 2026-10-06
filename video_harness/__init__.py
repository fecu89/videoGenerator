"""Resumable video generation harness."""

from .models import ResearchArtifact, Scene, ScriptArtifact, VideoPrompt
from .storage import RunStore

__all__ = [
    "ResearchArtifact",
    "RunStore",
    "Scene",
    "ScriptArtifact",
    "VideoPrompt",
    "ValidationIssue",
    "validate_run",
]


def __getattr__(name: str):
    """Keep renderer-heavy validation imports out of prompt-only startup."""
    if name in {"ValidationIssue", "validate_run"}:
        from .validation import ValidationIssue, validate_run

        return {"ValidationIssue": ValidationIssue, "validate_run": validate_run}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
