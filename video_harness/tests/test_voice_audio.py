import importlib
import numpy as np
import pytest
from video_harness.settings import VoiceSettings
def voice_audio_module(): return importlib.import_module("video_harness.voice_audio")


def test_short_korean_label_list_accounts_for_separate_articulation():
    budget = voice_audio_module().sentence_timing_budget(
        "순행, 유, 역행, 유, 다시 순행.", VoiceSettings()
    )
    # Four isolated short labels need distinct articulation; the final
    # two-word phrase retains its normal four syllables.
    assert budget.spoken_units == 16
    assert budget.punctuation_pauses == 4
    assert budget.target_output_seconds < 4

def test_comma_separated_prose_keeps_ordinary_timing():
    budget = voice_audio_module().sentence_timing_budget(
        "순행하다가, 유를 지나고, 역행합니다.", VoiceSettings()
    )
    assert budget.spoken_units == 15

def test_letter_enumeration_budget_allows_distinct_spoken_names():
    # Isolated alphabet names take longer than syllables inside ordinary words.
    budget = voice_audio_module().sentence_timing_budget(
        "오, 비, 에이, 에프, 지, 케이, 엠.", VoiceSettings()
    )
    assert budget.spoken_units == 21
    assert budget.punctuation_pauses == 6

def test_single_letter_mention_does_not_expand_an_ordinary_sentence():
    budget = voice_audio_module().sentence_timing_budget("오, 별입니다.", VoiceSettings())
    assert budget.spoken_units == 5

def test_split_sentences_keeps_words_together_and_splits_terminal_punctuation():
    split_sentences = voice_audio_module().split_sentences

    assert split_sentences("첫 문장입니다. 다음은 질문일까요? 네, 맞습니다!") == [
        "첫 문장입니다.",
        "다음은 질문일까요?",
        "네, 맞습니다!",
    ]
    assert split_sentences("쉼표 뒤는, 나누지 않습니다.") == [
        "쉼표 뒤는, 나누지 않습니다."
    ]

def test_sentence_edge_normalization_replaces_outer_silence_and_preserves_interior():
    normalize = voice_audio_module().normalize_sentence_edges
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
    normalize = voice_audio_module().normalize_sentence_edges
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
    normalize = voice_audio_module().normalize_sentence_edges

    with pytest.raises(ValueError, match="audible"):
        normalize(
            np.zeros(100, dtype=np.float32),
            sample_rate=1000,
            leading_ms=60,
            trailing_ms=200,
            tempo_factor=1.0,
        )

def test_longest_internal_silence_ignores_outer_edges():
    longest_silence = voice_audio_module().longest_internal_silence_ms
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
    longest_silence = voice_audio_module().longest_internal_silence_ms

    assert longest_silence(np.ones(100, dtype=np.float32), sample_rate=1000) == 0

@pytest.mark.parametrize('pause_ms', [50, 350])
def test_internal_silence_cap_removes_only_middle_of_excessive_pause(pause_ms):
    cap_silence = voice_audio_module().cap_internal_silence
    audio = np.concatenate(
        [
            np.zeros(100, dtype=np.float32),
            np.ones(50, dtype=np.float32),
            np.zeros(840, dtype=np.float32),
            np.full(50, 0.5, dtype=np.float32),
            np.zeros(200, dtype=np.float32),
        ]
    )

    capped = cap_silence(audio, sample_rate=1000, max_pause_ms=pause_ms)

    assert len(capped) == len(audio) - (840 - pause_ms)
    np.testing.assert_array_equal(capped[:150], audio[:150])
    np.testing.assert_array_equal(capped[-250:], audio[-250:])
    assert voice_audio_module().longest_internal_silence_ms(
        capped,
        sample_rate=1000,
    ) == pytest.approx(pause_ms)
