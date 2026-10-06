from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from .narration import split_narration_sentences


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: HttpUrl | None = None
    summary: str = Field(min_length=1)
    source_type: Literal["web", "pdf"]
    page: int | None = Field(default=None, ge=1)


class EvidenceFact(StrictModel):
    claim: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


class ResearchArtifact(StrictModel):
    input_kind: Literal["topic", "pdf"]
    input_label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    facts: list[EvidenceFact]
    visual_observations: list[str] = Field(default_factory=list)
    unresolved_claims: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(min_length=1)
    response_id: str | None = None


class CandidateScores(StrictModel):
    surprise: int = Field(ge=1, le=5)
    visualizability: int = Field(ge=1, le=5)
    causal_clarity: int = Field(ge=1, le=5)
    evidence_quality: int = Field(ge=1, le=5)


class TopicCandidate(StrictModel):
    title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    scores: CandidateScores
    source_ids: list[str] = Field(min_length=1)


class SelectedTopic(StrictModel):
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class StoryEngine(StrictModel):
    common_belief: str = Field(min_length=1)
    contradiction: str = Field(min_length=1)
    obvious_answer: str = Field(min_length=1)
    constraint: str = Field(min_length=1)
    actual_answer: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    payoff: str = Field(min_length=1)


class SentenceDelivery(StrictModel):
    sentence_index: int = Field(ge=1)
    emotion: Literal[
        "neutral",
        "curious",
        "bright",
        "surprised",
        "confident",
        "gentle",
    ]
    intensity: Literal["subtle", "moderate"] = "subtle"


class SentencePause(StrictModel):
    sentence_index: int = Field(ge=1)
    after: str = Field(min_length=1)
    kind: Literal['semantic', 'emphasis']


class Scene(StrictModel):
    scene_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=60)
    narration: str = Field(min_length=1)
    narrative_role: str = Field(min_length=1)
    visual_subject: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    duration_seconds: float | None = Field(default=None, gt=0)
    audio_file: str | None = None
    video_prompt_file: str | None = None
    sentence_delivery: list[SentenceDelivery] = Field(default_factory=list)
    sentence_pauses: list[SentencePause] = Field(default_factory=list)
    in_shorts: bool = True

    @model_validator(mode="after")
    def validate_sentence_delivery(self) -> "Scene":
        indices = [cue.sentence_index for cue in self.sentence_delivery]
        if len(indices) != len(set(indices)):
            raise ValueError("sentence_delivery sentence_index values must be unique")
        sentence_count = len(split_narration_sentences(self.narration))
        if indices and max(indices) > sentence_count:
            raise ValueError(
                "sentence_delivery sentence_index must not exceed narration "
                f"sentence count {sentence_count}"
            )
        from .voice_pauses import cue_offset
        sentences = split_narration_sentences(self.narration)
        seen = set()
        for cue in self.sentence_pauses:
            if cue.sentence_index > len(sentences):
                raise ValueError('sentence_pauses sentence_index exceeds sentence count')
            key = (cue.sentence_index, cue_offset(sentences[cue.sentence_index - 1], cue))
            if key in seen:
                raise ValueError('sentence_pauses cannot repeat the same boundary')
            seen.add(key)
        return self


class FactCheck(StrictModel):
    claim: str = Field(min_length=1)
    check_type: Literal["NUM", "CAUSE", "HISTORY", "TECH", "SUPER", "OTHER"]
    question: str = Field(min_length=1)


class ScriptArtifact(StrictModel):
    candidates: list[TopicCandidate] = Field(default_factory=list)
    selected_topic: SelectedTopic
    shorts_title: str | None = Field(default=None, min_length=1, max_length=40)
    upload_description: str | None = Field(default=None, min_length=1, max_length=2000)
    story_engine: StoryEngine
    scenes: list[Scene] = Field(min_length=1)
    fact_checks: list[FactCheck] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    response_id: str | None = None

    @model_validator(mode="after")
    def validate_scene_ids_and_selection(self) -> "ScriptArtifact":
        ids = [scene.scene_id for scene in self.scenes]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError("scene_id values must be unique and contiguous from 1")
        if self.candidates and self.selected_topic.title not in {
            candidate.title for candidate in self.candidates
        }:
            raise ValueError("selected topic must be present among candidates")
        return self


class VideoPrompt(StrictModel):
    scene_id: int = Field(ge=1)
    title: str = Field(min_length=1)
    narration: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    prompt: str = Field(min_length=1)
    negative_constraints: list[str] = Field(min_length=1)


class DurationViolation(StrictModel):
    scene_id: int = Field(ge=1)
    measured_seconds: float = Field(gt=0)
    direction: Literal["short", "long"]


class VideoPromptBatch(StrictModel):
    prompts: list[VideoPrompt] = Field(min_length=1)
    response_id: str | None = None
