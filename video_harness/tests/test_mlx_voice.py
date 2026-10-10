from __future__ import annotations

import importlib
import os
import platform
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from video_harness.models import Scene, SentenceDelivery
from video_harness.voice_audio import normalize_sentence_edges
from video_harness.settings import ArchivedVoiceSettings as VoiceSettings


def mlx_voice_module():
    try:
        return importlib.import_module("video_harness.mlx_voice")
    except ModuleNotFoundError:
        pytest.fail("video_harness.mlx_voice is not implemented")


def test_letter_enumeration_budget_allows_distinct_spoken_names():
    # Isolated alphabet names take longer than syllables inside ordinary words.
    budget = mlx_voice_module().sentence_timing_budget(
        "오, 비, 에이, 에프, 지, 케이, 엠.", VoiceSettings()
    )
    assert budget.spoken_units == 21
    assert budget.punctuation_pauses == 6


def test_single_letter_mention_does_not_expand_an_ordinary_sentence():
    budget = mlx_voice_module().sentence_timing_budget("오, 별입니다.", VoiceSettings())
    assert budget.spoken_units == 5


def test_full_letter_list_can_finish_before_internal_silence_is_trimmed():
    # Real Qwen/Sohee regression: 164 tokens, 13.12s raw, 7.99025s after
    # the approved 210ms silence cap. The cap must run after a complete utterance.
    settings=VoiceSettings(target_syllables_per_second=5.7,speaking_rate=1.17)
    budget=mlx_voice_module().sentence_timing_budget(
        "뜨거운 쪽부터 오, 비, 에이, 에프, 지, 케이, 엠 순서입니다.",settings)
    assert budget.spoken_units == 32
    assert budget.hard_token_limit > 164
    assert 7.99025 / budget.target_output_seconds <= 1.25
    assert budget.target_output_seconds < 7


def make_scene(
    scene_id: int,
    narration: str,
    role: str = "CONTEXT",
    *,
    sentence_delivery: list[dict[str, object]] | None = None,
) -> Scene:
    return Scene(
        scene_id=scene_id,
        title=f"장면 {scene_id}",
        narration=narration,
        narrative_role=role,
        visual_subject=f"대상 {scene_id}",
        sentence_delivery=sentence_delivery or [],
    )


def destinations(tmp_path: Path, *scene_ids: int) -> dict[int, Path]:
    return {
        scene_id: tmp_path / f"{scene_id:02d}_장면_{scene_id}.mp3"
        for scene_id in scene_ids
    }


class FakeModel:
    def __init__(
        self,
        *,
        sample_rate: int = 1000,
        samples_per_call: int = 100,
        results_per_call: int = 1,
        sample_rates: list[int] | None = None,
        audio_by_call: list[np.ndarray] | None = None,
        token_counts: list[int] | None = None,
        audio_value: float | None = None,
        speakers: list[str] | None = None,
        languages: list[str] | None = None,
    ):
        self.sample_rate = sample_rate
        self.samples_per_call = samples_per_call
        self.results_per_call = results_per_call
        self.sample_rates = sample_rates
        self.audio_by_call = audio_by_call
        self.token_counts = token_counts
        self.audio_value = audio_value
        self.speakers = ["sohee"] if speakers is None else speakers
        self.languages = ["korean"] if languages is None else languages
        self.calls: list[dict[str, object]] = []

    def get_supported_speakers(self) -> list[str]:
        return self.speakers

    def get_supported_languages(self) -> list[str]:
        return self.languages

    def generate_custom_voice(self, **kwargs):
        self.calls.append(kwargs)
        for _ in range(self.results_per_call):
            value = len(self.calls) if self.audio_value is None else self.audio_value
            audio = (
                np.full(self.samples_per_call, value, dtype=np.float32)
                if self.audio_by_call is None
                else self.audio_by_call[len(self.calls) - 1]
            )
            sample_rate = (
                self.sample_rate
                if self.sample_rates is None
                else self.sample_rates[len(self.calls) - 1]
            )
            yield SimpleNamespace(
                audio=audio,
                samples=self.samples_per_call,
                sample_rate=sample_rate,
                token_count=(
                    10
                    if self.token_counts is None
                    else self.token_counts[len(self.calls) - 1]
                ),
                processing_time_seconds=0.25,
                peak_memory_usage=1024,
            )


class FakeRuntime:
    def release_unused_memory(self):
        pass

    def __init__(self, model: FakeModel):
        self.model = model
        self.load_calls: list[tuple[str, str]] = []
        self.seeds: list[int] = []
        self.written_audio: dict[int, np.ndarray] = {}

    def load_model(self, model_id: str, *, revision: str):
        self.load_calls.append((model_id, revision))
        return self.model

    def write_audio(
        self,
        path: Path,
        audio: np.ndarray,
        sample_rate: int,
        audio_format: str | None,
    ) -> None:
        assert sample_rate == self.model.sample_rate
        assert audio_format == "WAV"
        self.written_audio[int(path.stem)] = audio.copy()
        path.write_bytes(b"wav")

    def seed(self, value: int) -> None:
        self.seeds.append(value)

    @staticmethod
    def to_numpy(audio) -> np.ndarray:
        return np.asarray(audio)

    @staticmethod
    def concatenate(chunks) -> np.ndarray:
        return np.concatenate(chunks)

    @staticmethod
    def zeros(count: int, dtype) -> np.ndarray:
        return np.zeros(count, dtype=dtype)

    @staticmethod
    def all_finite(audio) -> bool:
        return bool(np.isfinite(audio).all())


class FakeFFmpegRunner:
    def __init__(self, *, fail_on: int | None = None):
        self.commands: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, command, **kwargs):
        args = [str(part) for part in command]
        self.commands.append(args)
        if len(self.commands) == self.fail_on:
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr="configured ffmpeg failure",
            )
        Path(args[-1]).write_bytes(b"mp3")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


class RaisingRunner:
    def __init__(self, error: BaseException):
        self.error = error

    def __call__(self, command, **kwargs):
        raise self.error


class MissingOutputRunner:
    def __call__(self, command, **kwargs):
        args = [str(part) for part in command]
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


class FailOnceOnSecondReplace:
    def __init__(self):
        self.calls = 0

    def __call__(self, source: Path, destination: Path) -> None:
        self.calls += 1
        if self.calls == 2:
            raise OSError("configured publication failure")
        source.replace(destination)


def configured_synthesizer(
    tmp_path: Path,
    *,
    fake_model: FakeModel,
    duration_by_name: Mapping[str, float] | None = None,
    runner=None,
    command_locator=None,
    file_replacer=None,
    platform_name: str = "darwin",
    machine_name: str = "arm64",
    voice_settings: VoiceSettings | None = None,
):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    active_settings = voice_settings or VoiceSettings()
    active_settings = active_settings.model_copy(
        update={"instructions_file": str(prompt)}
    )
    runtime = FakeRuntime(fake_model)
    active_runner = runner or FakeFFmpegRunner()
    durations = duration_by_name or {}
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        active_settings,
        runtime_loader=lambda: runtime,
        runner=active_runner,
        command_locator=command_locator or (lambda name: f"/usr/bin/{name}"),
        duration_reader=lambda path: durations.get(path.name, 0.46),
        platform_name=platform_name,
        machine_name=machine_name,
        **({"file_replacer": file_replacer} if file_replacer is not None else {}),
    )
    return synthesizer, runtime, active_runner


def test_split_sentences_keeps_words_together_and_splits_terminal_punctuation():
    split_sentences = mlx_voice_module().split_sentences

    assert split_sentences("첫 문장입니다. 다음은 질문일까요? 네, 맞습니다!") == [
        "첫 문장입니다.",
        "다음은 질문일까요?",
        "네, 맞습니다!",
    ]
    assert split_sentences("쉼표 뒤는, 나누지 않습니다.") == [
        "쉼표 뒤는, 나누지 않습니다."
    ]


def test_short_sentence_timing_budget_does_not_expand_to_scene_maximum():
    budget_for = mlx_voice_module().sentence_timing_budget

    budget = budget_for(
        "이상하죠?",
        VoiceSettings(speaking_rate=1.15, target_syllables_per_second=5.2),
    )

    assert budget.spoken_units == 4
    assert budget.punctuation_pauses == 0
    assert budget.target_output_seconds == pytest.approx(4 / 5.2)
    assert budget.soft_token_budget == 12
    assert budget.hard_token_limit == 16


def test_sentence_timing_budget_counts_only_script_authored_internal_punctuation():
    budget_for = mlx_voice_module().sentence_timing_budget
    text = "화성과 지구는 한 방향으로만 움직이는데, 어째서 중간에 방향이 바뀔까요?"

    budget = budget_for(
        text,
        VoiceSettings(speaking_rate=1.15, target_syllables_per_second=5.2),
    )

    assert budget.spoken_units == 30
    assert budget.punctuation_pauses == 1
    assert budget.target_output_seconds == pytest.approx(30 / 5.2 + 0.18)
    assert budget.soft_token_budget == 86
    assert budget.hard_token_limit == 112


def test_sentence_edge_normalization_replaces_outer_silence_and_preserves_interior():
    normalize = normalize_sentence_edges
    audio = np.concatenate(
        [
            np.zeros(50, dtype=np.float32),
            np.ones(40, dtype=np.float32),
            np.zeros(30, dtype=np.float32),
            np.full(40, 0.5, dtype=np.float32),
            np.zeros(70, dtype=np.float32),
        ]
    )

    normalized = normalize(
        audio,
        sample_rate=1000,
        leading_ms=60,
        trailing_ms=200,
        tempo_factor=1.0,
    )

    nonzero = np.flatnonzero(normalized)
    assert nonzero[0] == 60
    assert nonzero[-1] == 169
    assert len(normalized) - nonzero[-1] - 1 == 200
    np.testing.assert_array_equal(normalized[60:170], audio[50:160])


def test_sentence_edge_normalization_precompensates_margins_for_atempo():
    normalize = normalize_sentence_edges
    audio = np.ones(100, dtype=np.float32)

    normalized = normalize(
        audio,
        sample_rate=1000,
        leading_ms=60,
        trailing_ms=200,
        tempo_factor=1.15,
    )

    nonzero = np.flatnonzero(normalized)
    assert nonzero[0] == 69
    assert len(normalized) - nonzero[-1] - 1 == 230


def test_sentence_edge_normalization_rejects_silent_audio():
    normalize = normalize_sentence_edges

    with pytest.raises(ValueError, match="audible"):
        normalize(
            np.zeros(100, dtype=np.float32),
            sample_rate=1000,
            leading_ms=60,
            trailing_ms=200,
            tempo_factor=1.0,
        )


def test_longest_internal_silence_ignores_outer_edges():
    longest_silence = mlx_voice_module().longest_internal_silence_ms
    audio = np.concatenate(
        [
            np.zeros(100, dtype=np.float32),
            np.ones(50, dtype=np.float32),
            np.zeros(420, dtype=np.float32),
            np.ones(50, dtype=np.float32),
            np.zeros(500, dtype=np.float32),
        ]
    )

    assert longest_silence(audio, sample_rate=1000) == pytest.approx(420)


def test_longest_internal_silence_is_zero_for_continuous_speech():
    longest_silence = mlx_voice_module().longest_internal_silence_ms

    assert longest_silence(np.ones(100, dtype=np.float32), sample_rate=1000) == 0


def test_internal_silence_cap_removes_only_middle_of_excessive_pause():
    cap_silence = mlx_voice_module().cap_internal_silence
    audio = np.concatenate(
        [
            np.zeros(100, dtype=np.float32),
            np.ones(50, dtype=np.float32),
            np.zeros(840, dtype=np.float32),
            np.full(50, 0.5, dtype=np.float32),
            np.zeros(200, dtype=np.float32),
        ]
    )

    capped = cap_silence(audio, sample_rate=1000, max_pause_ms=350)

    assert len(capped) == len(audio) - 490
    np.testing.assert_array_equal(capped[:150], audio[:150])
    np.testing.assert_array_equal(capped[-250:], audio[-250:])
    assert mlx_voice_module().longest_internal_silence_ms(
        capped,
        sample_rate=1000,
    ) == pytest.approx(350)


def test_neutral_instruction_is_identical_for_role_question_and_position(tmp_path: Path):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        VoiceSettings(instructions_file=str(prompt))
    )

    first = synthesizer.effective_instruction(None)
    second = synthesizer.effective_instruction(None)

    assert first == second == "전역 지시"


def test_script_delivery_adds_only_the_requested_restrained_emotion(tmp_path: Path):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        VoiceSettings(instructions_file=str(prompt))
    )
    cue = SentenceDelivery(
        sentence_index=2,
        emotion="curious",
        intensity="subtle",
    )

    instruction = synthesizer.effective_instruction(cue)

    assert instruction.startswith("전역 지시")
    assert "호기심" in instruction
    assert "기본 화자" in instruction


def test_emotion_off_ignores_script_delivery(tmp_path: Path):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        VoiceSettings(instructions_file=str(prompt), emotion_mode="off")
    )
    cue = SentenceDelivery(
        sentence_index=1,
        emotion="surprised",
        intensity="moderate",
    )

    assert synthesizer.effective_instruction(cue) == "전역 지시"


def test_consistent_generation_preset_overrides_advanced_sampling_values(tmp_path: Path):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        VoiceSettings(
            instructions_file=str(prompt),
            generation_preset="consistent",
            temperature=1.4,
            top_k=99,
            top_p=0.7,
            repetition_penalty=1.4,
        )
    )

    assert synthesizer.effective_sampling() == (0.5, 30, 1.0, 1.05)


def test_custom_generation_preset_uses_advanced_sampling_values(tmp_path: Path):
    prompt = tmp_path / "voice.txt"
    prompt.write_text("전역 지시", encoding="utf-8")
    synthesizer = mlx_voice_module().MLXAudioSynthesizer(
        VoiceSettings(
            instructions_file=str(prompt),
            generation_preset="custom",
            temperature=0.65,
            top_k=41,
            top_p=0.85,
            repetition_penalty=1.1,
        )
    )

    assert synthesizer.effective_sampling() == (0.65, 41, 0.85, 1.1)


def test_synthesizer_loads_once_generates_per_sentence_and_inserts_1050ms(
    tmp_path: Path,
):
    fake_model = FakeModel(sample_rate=1000, samples_per_call=100)
    synthesizer, runtime, runner = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        duration_by_name={"01_장면_1.mp3": 0.1, "02_장면_2.mp3": 0.46},
        voice_settings=VoiceSettings(speaking_rate=1.0),
    )
    scenes = [
        make_scene(2, "한 문장입니다. 다음 문장입니다.", "MECHANISM"),
        make_scene(1, "하나입니다.", "HOOK"),
    ]

    results = synthesizer.synthesize(scenes, destinations(tmp_path, 1, 2))

    assert runtime.load_calls == [
        (
            "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
            "41d3337e8b7f2843a75841595fc14e4b9a7a4b96",
        )
    ]
    assert [call["text"] for call in fake_model.calls] == [
        "하나입니다.",
        "한 문장입니다.",
        "다음 문장입니다.",
    ]
    assert runtime.seeds == [20260828, 20260828, 20260828]
    assert runtime.written_audio[2].shape == (2300,)
    assert np.all(runtime.written_audio[2][200:1250] == 0)
    assert [result.scene_id for result in results] == [1, 2]
    assert [result.duration_seconds for result in results] == [0.1, 0.46]
    assert all(result.path.read_bytes() == b"mp3" for result in results)
    assert len(runner.commands) == 2
    assert [call["max_tokens"] for call in fake_model.calls] == [17, 20, 23]
    for call in fake_model.calls:
        assert call["speaker"] == "Sohee"
        assert call["language"] == "Korean"
        assert call["temperature"] == 0.5
        assert call["top_k"] == 30
        assert call["top_p"] == 1.0
        assert call["repetition_penalty"] == 1.05
        assert call["verbose"] is False
        assert call["stream"] is False
    assert len(
        {
            sentence.instruction_sha256
            for result in results
            for sentence in result.generation.sentences
        }
    ) == 1


def test_synthesizer_applies_delivery_only_to_the_addressed_sentence(tmp_path: Path):
    fake_model = FakeModel(sample_rate=1000, samples_per_call=100)
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(speaking_rate=1.0),
    )
    scene = make_scene(
        1,
        "첫 문장입니다. 둘째 문장입니다.",
        sentence_delivery=[
            {"sentence_index": 2, "emotion": "confident", "intensity": "subtle"}
        ],
    )

    synthesizer.synthesize([scene], destinations(tmp_path, 1))

    assert fake_model.calls[0]["instruct"] == "전역 지시"
    assert fake_model.calls[1]["instruct"].startswith("전역 지시")
    assert "확신" in fake_model.calls[1]["instruct"]


def test_sentence_retries_when_generation_hits_text_derived_token_limit(
    tmp_path: Path,
):
    fake_model = FakeModel(
        sample_rate=1000,
        samples_per_call=100,
        token_counts=[16, 11],
    )
    synthesizer, runtime, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(speaking_rate=1.15),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "이상하죠?")],
        destinations(tmp_path, 1),
    )

    assert [call["max_tokens"] for call in fake_model.calls] == [16, 24]
    assert runtime.seeds == [20260828, 20260829]
    sentence = results[0].generation.sentences[0]
    assert sentence.seed == 20260829
    assert sentence.attempt_count == 2
    assert sentence.soft_token_budget == 12
    assert sentence.hard_token_limit == 24


@pytest.mark.parametrize("last_samples,acceptable", [(1055, True), (1500, False)])
def test_short_phrase_recovers_after_mixed_truncation_and_tempo_rejections(
    tmp_path: Path, last_samples: int, acceptable: bool,
):
    # Real Sohee failure for "잘 튀는 공을": clipped, too slow, clipped.
    # A subsequent complete candidate must still satisfy the same tempo limit.
    from video_harness.settings import VoiceSettings as CurrentVoiceSettings
    fake = FakeModel(
        sample_rate=1000,
        audio_by_call=[np.full(n, .2, dtype=np.float32)
                       for n in (958, 1263, 1581, last_samples, last_samples, last_samples)],
        token_counts=[13, 17, 20, 15, 15, 15],
    )
    synth, runtime, _ = configured_synthesizer(
        tmp_path, fake_model=fake,
        voice_settings=CurrentVoiceSettings(
            target_syllables_per_second=6.5, speaking_rate=1., max_tempo_factor=1.4,
        ),
    )
    def generate():
        return synth._generate_sentence(
            model=fake, runtime=runtime, sentence="잘 튀는 공을",
            instruction="전역 지시", scene_id=15, sentence_index=1,
        )
    if not acceptable:
        with pytest.raises(RuntimeError, match="above 1.40"):
            generate()
        return
    audio, rate, report = generate()
    assert rate == 1000
    assert len(audio) == 1055
    assert report.raw_speech_seconds == pytest.approx(1.055)
    assert report.raw_speech_seconds / report.target_output_seconds <= 1.4
    assert report.token_count < report.hard_token_limit


def test_sentence_caps_model_inserted_pause_without_regenerating_words(
    tmp_path: Path,
):
    fake_model = FakeModel(
        sample_rate=1000,
        audio_by_call=[
            np.concatenate(
                [
                    np.ones(50, dtype=np.float32),
                    np.zeros(400, dtype=np.float32),
                    np.ones(50, dtype=np.float32),
                ]
            )
        ],
        token_counts=[10],
    )
    synthesizer, runtime, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(
            speaking_rate=1.15,
            max_internal_pause_ms=350,
        ),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "이상하죠?")],
        destinations(tmp_path, 1),
    )

    assert len(fake_model.calls) == 1
    assert runtime.seeds == [20260828]
    sentence = results[0].generation.sentences[0]
    assert sentence.attempt_count == 1
    assert sentence.original_longest_internal_pause_ms == pytest.approx(400)
    assert sentence.longest_internal_pause_ms == pytest.approx(350)


def test_each_sentence_gets_its_own_content_aware_tempo_factor(tmp_path: Path):
    fake_model = FakeModel(
        sample_rate=1000,
        audio_by_call=[
            np.ones(100, dtype=np.float32),
            np.ones(1400, dtype=np.float32),
        ],
        token_counts=[10, 10],
    )
    synthesizer, _, runner = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(
            speaking_rate=1.0,
            target_syllables_per_second=5.2,
        ),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "첫 문장입니다. 둘 문장입니다.")],
        destinations(tmp_path, 1),
    )

    sentence_tempos = [
        sentence.tempo_factor for sentence in results[0].generation.sentences
    ]
    assert sentence_tempos == pytest.approx([1.0, 1.4 / (6 / 5.2)])
    command = runner.commands[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "atempo=1.000000000" in filter_graph
    assert "atempo=1.213333333" in filter_graph
    assert results[0].generation.tempo_factor == pytest.approx(1.213333333)


def test_internal_pause_filter_does_not_trim_sentence_boundary_margins(
    tmp_path: Path,
):
    fake_model = FakeModel(
        sample_rate=1000,
        audio_by_call=[
            np.ones(100, dtype=np.float32),
            np.ones(100, dtype=np.float32),
        ],
        token_counts=[10, 10],
    )
    synthesizer, _, runner = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(speaking_rate=1.0),
    )

    synthesizer.synthesize(
        [make_scene(1, "첫 문장입니다. 둘 문장입니다.")],
        destinations(tmp_path, 1),
    )

    command = runner.commands[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert filter_graph.count("atrim=start_sample=") == 2
    assert "[joined]silenceremove" not in filter_graph
    assert filter_graph.count("adelay=100:all=1,apad=pad_dur=0.950") == 2


def test_slow_sentence_is_retried_instead_of_using_unnatural_tempo(
    tmp_path: Path,
):
    fake_model = FakeModel(
        sample_rate=1000,
        audio_by_call=[
            np.ones(9000, dtype=np.float32),
            np.ones(1200, dtype=np.float32),
        ],
        token_counts=[10, 10],
    )
    synthesizer, runtime, runner = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        duration_by_name={"01_장면_1.mp3": 1.4},
        voice_settings=VoiceSettings(max_scene_seconds=8.0),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "긴 설명입니다.", "PROOF")],
        destinations(tmp_path, 1),
    )

    assert runtime.seeds == [20260828, 20260829]
    assert results[0].generation.sentences[0].attempt_count == 2
    assert results[0].generation.tempo_factor == pytest.approx(1.08)
    filter_graph = runner.commands[0][
        runner.commands[0].index("-filter_complex") + 1
    ]
    assert "atempo=1.080000000" in filter_graph


@pytest.mark.parametrize("speaking_rate", [0.95, 1.15])
def test_configured_speaking_rate_is_applied_to_short_audio(
    tmp_path: Path,
    speaking_rate: float,
):
    fake_model = FakeModel(sample_rate=1000, samples_per_call=100)
    synthesizer, _, runner = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        duration_by_name={"01_장면_1.mp3": 0.1},
        voice_settings=VoiceSettings(speaking_rate=speaking_rate),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "짧은 설명입니다.", "HOOK")],
        destinations(tmp_path, 1),
    )

    command = runner.commands[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert f"atempo={speaking_rate:.9f}" in filter_graph
    assert results[0].generation.tempo_factor == pytest.approx(speaking_rate)


def test_speaking_rate_preserves_sentence_margins_after_atempo(tmp_path: Path):
    fake_model = FakeModel(sample_rate=1000, samples_per_call=100)
    synthesizer, runtime, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        duration_by_name={"01_장면_1.mp3": 0.46},
        voice_settings=VoiceSettings(speaking_rate=1.15),
    )

    synthesizer.synthesize(
        [make_scene(1, "첫 문장입니다. 둘째 문장입니다.", "HOOK")],
        destinations(tmp_path, 1),
    )

    written = runtime.written_audio[1]
    assert written.shape == (2614,)
    assert np.all(written[215:1422] == 0)
    assert np.all(written[1522:] == 0)


def test_final_sentence_keeps_configured_trailing_safety_margin(tmp_path: Path):
    fake_model = FakeModel(sample_rate=1000, samples_per_call=100)
    synthesizer, runtime, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
        voice_settings=VoiceSettings(speaking_rate=1.0),
    )

    results = synthesizer.synthesize(
        [make_scene(1, "끝음이 잘리지 않습니다.")],
        destinations(tmp_path, 1),
    )

    written = runtime.written_audio[1]
    assert written.shape == (1150,)
    assert np.all(written[:100] == 0)
    assert np.all(written[-950:] == 0)
    assert results[0].generation.sentence_leading_margin_ms == 100
    assert results[0].generation.sentence_trailing_margin_ms == 950


def test_excessive_atempo_is_rejected_before_publication(tmp_path: Path):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, runner = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(sample_rate=1000, samples_per_call=10000),
        voice_settings=VoiceSettings(max_scene_seconds=8.0),
    )

    with pytest.raises(RuntimeError, match="delivery quality budget"):
        synthesizer.synthesize(
            [make_scene(1, "지나치게 긴 설명입니다.", "PROOF")],
            {1: destination},
        )

    assert runner.commands == []
    assert destination.read_bytes() == b"existing"


@pytest.mark.parametrize(
    ("platform_name", "machine_name", "message"),
    [
        ("linux", "x86_64", "Apple silicon"),
        ("darwin", "x86_64", "arm64"),
    ],
)
def test_backend_requires_apple_silicon(
    tmp_path: Path,
    platform_name: str,
    machine_name: str,
    message: str,
):
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        platform_name=platform_name,
        machine_name=machine_name,
    )

    with pytest.raises(RuntimeError, match=message):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            destinations(tmp_path, 1),
        )


def test_backend_rejects_missing_ffmpeg(tmp_path: Path):
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        command_locator=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="ffmpeg"):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            destinations(tmp_path, 1),
        )


@pytest.mark.parametrize(
    ("speakers", "languages", "message"),
    [([], ["korean"], "Sohee"), (["sohee"], [], "Korean")],
)
def test_backend_rejects_unsupported_speaker_or_language(
    tmp_path: Path,
    speakers: list[str],
    languages: list[str],
    message: str,
):
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(speakers=speakers, languages=languages),
    )

    with pytest.raises(RuntimeError, match=message):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            destinations(tmp_path, 1),
        )


@pytest.mark.parametrize("results_per_call", [0, 2])
def test_backend_requires_one_nonstreaming_result_and_preserves_destination(
    tmp_path: Path,
    results_per_call: int,
):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(results_per_call=results_per_call),
    )

    with pytest.raises(RuntimeError, match="exactly one"):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            {1: destination},
        )

    assert destination.read_bytes() == b"existing"


@pytest.mark.parametrize(
    "fake_model",
    [
        FakeModel(samples_per_call=0),
        FakeModel(audio_value=float("nan")),
        FakeModel(sample_rate=0),
    ],
    ids=["empty", "nonfinite", "zero-rate"],
)
def test_backend_rejects_invalid_audio_before_publication(
    tmp_path: Path,
    fake_model: FakeModel,
):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=fake_model,
    )

    with pytest.raises(RuntimeError, match="invalid audio"):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            {1: destination},
        )

    assert destination.read_bytes() == b"existing"


def test_backend_rejects_mixed_sentence_sample_rates(tmp_path: Path):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(sample_rate=1000, sample_rates=[1000, 1200]),
    )

    with pytest.raises(RuntimeError, match="sample rates"):
        synthesizer.synthesize(
            [make_scene(1, "첫 문장입니다. 둘째 문장입니다.")],
            {1: destination},
        )

    assert destination.read_bytes() == b"existing"


def test_ffmpeg_failure_keeps_all_existing_destinations_unchanged(tmp_path: Path):
    final_destinations = destinations(tmp_path, 1, 2)
    final_destinations[1].write_bytes(b"old-one")
    final_destinations[2].write_bytes(b"old-two")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        runner=FakeFFmpegRunner(fail_on=2),
    )

    with pytest.raises(RuntimeError, match="configured ffmpeg failure"):
        synthesizer.synthesize(
            [make_scene(1, "하나입니다."), make_scene(2, "둘입니다.")],
            final_destinations,
        )

    assert final_destinations[1].read_bytes() == b"old-one"
    assert final_destinations[2].read_bytes() == b"old-two"


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (RaisingRunner(OSError("no process")), "실행할 수 없습니다"),
        (
            RaisingRunner(subprocess.TimeoutExpired(["ffmpeg"], 60.0)),
            "시간이 초과",
        ),
    ],
)
def test_ffmpeg_process_errors_are_normalized_and_preserve_destination(
    tmp_path: Path,
    runner,
    message: str,
):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        runner=runner,
    )

    with pytest.raises(RuntimeError, match=message):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            {1: destination},
        )

    assert destination.read_bytes() == b"existing"


def test_successful_ffmpeg_without_output_is_rejected_before_publication(
    tmp_path: Path,
):
    destination = destinations(tmp_path, 1)[1]
    destination.write_bytes(b"existing")
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        runner=MissingOutputRunner(),
    )

    with pytest.raises(RuntimeError, match="MP3"):
        synthesizer.synthesize(
            [make_scene(1, "문장입니다.")],
            {1: destination},
        )

    assert destination.read_bytes() == b"existing"


@pytest.mark.skipif(
    os.environ.get("VG_REAL_MLX_TTS") != "1"
    or platform.system() != "Darwin"
    or platform.machine() != "arm64",
    reason="set VG_REAL_MLX_TTS=1 on Apple silicon for the cached-model smoke test",
)
def test_real_model_generates_nonempty_sohee_mp3(tmp_path: Path):
    module = mlx_voice_module()
    synthesizer = module.MLXAudioSynthesizer(VoiceSettings())
    destination = tmp_path / "03_후진의_비밀.mp3"

    results = synthesizer.synthesize(
        [
            make_scene(
                3,
                "행성이 실제로 후진하는 걸까요? 아닙니다. 공전 속도 차이 때문입니다.",
                "REVEAL",
            )
        ],
        {3: destination},
    )

    assert destination.stat().st_size > 0
    assert results[0].duration_seconds > 0
    assert results[0].generation.sentence_gap_milliseconds == 260
    assert len(results[0].generation.sentences) == 3


def test_publication_failure_restores_all_existing_destinations(tmp_path: Path):
    final_destinations = destinations(tmp_path, 1, 2)
    final_destinations[1].write_bytes(b"old-one")
    final_destinations[2].write_bytes(b"old-two")
    replacer = FailOnceOnSecondReplace()
    synthesizer, _, _ = configured_synthesizer(
        tmp_path,
        fake_model=FakeModel(),
        file_replacer=replacer,
    )

    with pytest.raises(OSError, match="configured publication failure"):
        synthesizer.synthesize(
            [make_scene(1, "하나입니다."), make_scene(2, "둘입니다.")],
            final_destinations,
        )

    assert final_destinations[1].read_bytes() == b"old-one"
    assert final_destinations[2].read_bytes() == b"old-two"


def test_truncated_candidates_do_not_exhaust_completed_candidate_tempo_budget(tmp_path):
    # A short approved phrase can use 2 of 4 attempts just finishing the text.
    # Four completed candidates must still be available, with the same speed cap.
    from video_harness.settings import VoiceSettings as CurrentVoiceSettings
    fake=FakeModel(sample_rate=1000,
        audio_by_call=[np.full(n,.2,dtype=np.float32) for n in (2900,2500,4400,2500,2100)],
        token_counts=[29,35,44,40,30])
    synth,runtime,_=configured_synthesizer(tmp_path,fake_model=fake,
        voice_settings=CurrentVoiceSettings(target_syllables_per_second=6.5,speaking_rate=1.,max_tempo_factor=1.4))
    audio,rate,report=synth._generate_sentence(model=fake,runtime=runtime,
        sentence='그 안에 전류가 유도됩니다.',instruction='전역 지시',scene_id=16,sentence_index=2)
    assert len(audio)==2100
    assert report.tempo_factor<=1.4
    assert report.token_count<report.hard_token_limit
    assert report.attempt_count==5
