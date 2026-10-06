from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .models import Scene, ScriptArtifact


ModelT = TypeVar("ModelT", bound=BaseModel)


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[^\w.-]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("._-")
    return normalized[:80] or fallback


def fingerprint(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def scene_filename(scene: Scene, suffix: str, width: int = 2) -> str:
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return (
        f"{scene.scene_id:0{width}d}_"
        f"{sanitize_filename(scene.title)}{normalized_suffix}"
    )


def shot_filename(shot_id: str, title: str, suffix: str) -> str:
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{shot_id}_{sanitize_filename(title)}{normalized_suffix}"


def scene_narration_text(scene: Scene) -> str:
    return (
        f"SCENE {scene.scene_id:02d} - {scene.title}\n"
        f"Narration: {scene.narration}\n"
    )


class RunStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.audio_dir = self.root / "audioFiles"
        self.video_prompt_dir = self.root / "videoPrompt"
        self.video_dir = self.root / "videoFiles"
        self.shot_asset_dir = self.root / "shotAssets"
        self.shot_dir = self.root / "shotFiles"

    @classmethod
    def create(cls, runs_dir: Path, label: str, input_kind: str) -> "RunStore":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        root = runs_dir.resolve() / f"{timestamp}-{sanitize_filename(label)}"
        store = cls(root)
        store.audio_dir.mkdir(parents=True, exist_ok=False)
        (store.root / "input").mkdir()
        store.write_json(
            "input.json",
            {"input_kind": input_kind, "label": label},
        )
        return store

    @classmethod
    def open(cls, root: Path) -> "RunStore":
        store = cls(root)
        if not store.root.is_dir():
            raise FileNotFoundError(f"Run directory not found: {store.root}")
        store.audio_dir.mkdir(exist_ok=True)
        return store

    def path(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"Path escapes run directory: {relative}")
        return candidate

    def ensure_production_directories(self) -> None:
        for relative in (
            "shotAssets/entities",
            "shotAssets/starts",
            "shotAssets/ends",
            "shotAssets/backgrounds",
            "shotAssets/masks",
            "shotFiles/inbox",
            "shotFiles/reviews",
            "shotFiles/previews",
        ):
            self.path(relative).mkdir(parents=True, exist_ok=True)

    def write_text(self, relative: str | Path, content: str) -> Path:
        path = self.path(relative)
        atomic_write(path, content)
        return path

    def write_json(self, relative: str | Path, data: Any) -> Path:
        return self.write_text(
            relative,
            json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
        )

    def write_model(self, relative: str | Path, model: BaseModel) -> Path:
        return self.write_text(
            relative,
            model.model_dump_json(indent=2) + "\n",
        )

    def read_json(self, relative: str | Path) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def read_model(self, relative: str | Path, model_type: type[ModelT]) -> ModelT:
        return model_type.model_validate_json(
            self.path(relative).read_text(encoding="utf-8")
        )

    def read_script(self) -> ScriptArtifact:
        return self.read_model("script.json", ScriptArtifact)

    def write_script(self, script: ScriptArtifact) -> Path:
        return self.write_model("script.json", script)
