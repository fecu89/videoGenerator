from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from importlib import import_module


def _command(module_name: str, function_name: str) -> Callable[[Sequence[str] | None], int]:
    def dispatch(argv: Sequence[str] | None = None) -> int:
        module = import_module(f"{__package__}.{module_name}")
        return getattr(module, function_name)(argv)

    return dispatch


COMMANDS: dict[str, Callable[[Sequence[str] | None], int]] = {
    "check-creative": _command("creative_gates", "main"),
    "blender": _command("blender_backend", "main"),
    "voice": _command("voice", "main"),
    "validate": _command("validation", "main"),
    "render": _command("render", "main"),
    "migrate-production": _command("migration", "migration_main"),
    "retime-production": _command("migration", "retime_main"),
    "plan-video": _command("migration", "plan_video_main"),
    "approve-video-plan": _command("video_plan_approval", "main"),
    "preview": _command("preview", "main"),
    "preview-ui": _command("preview_ui", "main"),
    "progress-ui": _command("progress_ui", "main"),
    "story-ui": _command("preview_ui", "story_main"),
    "approve-preview": _command("stage_approvals", "preview_main"),
    "approve-draft": _command("stage_approvals", "draft_main"),
    "translate-scaffold": _command("translations", "main"),
    "render-production": _command("production_render", "render_main"),
    "review-shot": _command("production_render", "review_main"),
    "produce-local": _command("produce_local", "main"),
    "produce": _command("pipeline", "main"),
    "settings": _command("settings_cli", "main"),
    "settings-ui": _command("settings_ui", "main"),
    "benchmark-render": _command("render_benchmark", "main"),
}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in COMMANDS:
        print(
            "usage: python -m video_harness {" + "|".join(COMMANDS) + "} ...",
            file=sys.stderr,
        )
        return 2
    command, *command_args = arguments
    return COMMANDS[command](command_args)


if __name__ == "__main__":
    raise SystemExit(main())
