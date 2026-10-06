import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness.settings import HarnessSettings, VoiceSettings, load_project_settings
from video_harness.pacing_presets import apply_pacing_preset, pacing_status
from video_harness.speech_test import SpeechTester
from video_harness.tests.test_settings_ui import api_headers, request, running_server  # noqa: F401


class FakeSynth:
    def __init__(self, voice):
        self.settings = voice
        self.closed = False
        self.seen = []

    def synthesize(self, scenes, destinations):
        self.seen.append((scenes[0].narration, self.settings.target_syllables_per_second))
        destinations[1].write_bytes(b"ID3fake")
        return [SimpleNamespace(duration_seconds=4.2)]

    def close(self):
        self.closed = True


def test_tester_reuses_the_model_for_pace_changes_and_reloads_for_a_new_voice():
    made = []
    tester = SpeechTester(factory=lambda voice: made.append(FakeSynth(voice)) or made[-1])
    tester.speak(apply_pacing_preset(HarnessSettings(), "standard").voice, "하나. 둘.")
    tester.speak(apply_pacing_preset(HarnessSettings(), "shorts").voice, "")
    assert len(made) == 1 and made[0].seen[1][1] == 6.5
    assert made[0].seen[1][0].startswith("앞차가")          # empty text falls back to the sample
    tester.speak(apply_pacing_preset(HarnessSettings(), "shorts").voice.model_copy(update={"speaker": "Vivian"}), "셋.")
    assert len(made) == 2 and made[0].closed
    tester.close()
    assert made[1].closed


def test_speech_test_endpoint_returns_audio_without_saving(running_server):  # noqa: F811
    running_server.speech_tester = SpeechTester(factory=FakeSynth)
    before = Path(running_server.settings_file).read_text()
    settings = apply_pacing_preset(HarnessSettings(), "standard").model_dump(mode="json")
    status, payload, _ = request(running_server, "POST", "/api/speech-test",
                                 body={"settings": settings, "text": "테스트 문장입니다."},
                                 headers=api_headers(running_server))
    assert status == 200
    assert base64.b64decode(payload["audio_base64"]) == b"ID3fake" and payload["seconds"] == 4.2
    assert Path(running_server.settings_file).read_text() == before


def test_speech_test_endpoint_reports_failures(running_server):  # noqa: F811
    class Failing(FakeSynth):
        def synthesize(self, scenes, destinations):
            raise RuntimeError("requires atempo 1.372, above 1.25")
    running_server.speech_tester = SpeechTester(factory=Failing)
    settings = HarnessSettings().model_dump(mode="json")
    status, payload, _ = request(running_server, "POST", "/api/speech-test",
                                 body={"settings": settings}, headers=api_headers(running_server))
    assert status == 422 and "1.372" in payload["message"]


def test_speech_test_requires_the_session_token(running_server):  # noqa: F811
    status, _, _ = request(running_server, "POST", "/api/speech-test", body={"settings": {}})
    assert status == 403


def test_settings_payload_lists_the_levels(running_server):  # noqa: F811
    status, payload, _ = request(running_server, "GET", "/api/settings", headers=api_headers(running_server))
    assert status == 200
    assert [preset["id"] for preset in payload["pacing_presets"]["presets"]] == ["calm", "standard", "shorts"]
    assert json.dumps(payload["speech_test_sample"], ensure_ascii=False)
