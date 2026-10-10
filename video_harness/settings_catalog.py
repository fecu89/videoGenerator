from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .settings import HarnessSettings


ControlKind = Literal["select", "range", "number", "text"]


@dataclass(frozen=True)
class SectionPresentation:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class SettingOption:
    value: str
    label: str


@dataclass(frozen=True)
class SettingPresentation:
    key: str
    section: str
    label: str
    description: str
    control: ControlKind
    unit: str | None = None
    step: float | int | None = None
    ui_min: float | int | None = None
    ui_max: float | int | None = None
    options: tuple[SettingOption, ...] = ()
    advanced: bool = False


SETTINGS_SECTIONS = (
    SectionPresentation("pace", "영상 템포", "말하기와 화면의 리듬을 한 번에 정합니다."),
    SectionPresentation("basic", "목소리", "Sohee의 말투와 문장별 감정 표현입니다."),
    SectionPresentation("sound", "배경음악", "사용할 음악과 크기를 정합니다."),
    SectionPresentation("output", "출력", "영상 규격과 언어별 산출물을 정합니다."),
    SectionPresentation("advanced", "고급 옵션", "기본 선택을 유지하면서 필요한 세부 값만 조정합니다."),
)


def _option(value: str, label: str) -> SettingOption:
    return SettingOption(value=value, label=label)


def _select(
    key: str,
    section: str,
    label: str,
    description: str,
    *options: SettingOption,
    advanced: bool = False,
) -> SettingPresentation:
    return SettingPresentation(
        key=key,
        section=section,
        label=label,
        description=description,
        control="select",
        options=options,
        advanced=advanced,
    )


def _range(
    key: str,
    section: str,
    label: str,
    description: str,
    ui_min: float | int,
    ui_max: float | int,
    step: float | int,
    *,
    unit: str | None = None,
    advanced: bool = False,
) -> SettingPresentation:
    return SettingPresentation(
        key=key,
        section=section,
        label=label,
        description=description,
        control="range",
        unit=unit,
        step=step,
        ui_min=ui_min,
        ui_max=ui_max,
        advanced=advanced,
    )


def _number(
    key: str,
    section: str,
    label: str,
    description: str,
    *,
    unit: str | None = None,
    advanced: bool = False,
) -> SettingPresentation:
    return SettingPresentation(
        key=key,
        section=section,
        label=label,
        description=description,
        control="number",
        unit=unit,
        advanced=advanced,
    )


def _text(
    key: str,
    section: str,
    label: str,
    description: str,
    *,
    advanced: bool = False,
) -> SettingPresentation:
    return SettingPresentation(
        key=key,
        section=section,
        label=label,
        description=description,
        control="text",
        advanced=advanced,
    )


# The UI presents operator choices, not every implementation parameter.
SETTINGS_CATALOG = (
    _select("voice.instructions_file", "basic", "목소리 톤", "영상 전체에 유지할 Sohee의 말투입니다.",
            _option("video_harness/agent/prompts/voice-sohee-ko-bright.txt", "밝고 생동감 있게"),
            _option("video_harness/agent/prompts/voice-sohee-ko.txt", "차분하고 신뢰감 있게"),
            _option("video_harness/agent/prompts/voice-sohee-ko-energetic.txt", "활기차고 신나게"),
            _option("video_harness/agent/prompts/voice-sohee-ko-documentary.txt", "진중한 다큐멘터리")),
    _select("voice.emotion_mode", "basic", "문장별 감정 표현", "켜면 대본의 문장별 감정 지시를 따릅니다. 꺼도 전체 말투는 유지합니다.",
            _option("off", "사용 안 함"), _option("script_only", "대본의 감정 지시 사용")),
    _text("music.file", "sound", "배경음악", "파일을 선택합니다. 비우면 음악 없이 만듭니다."),
    _range("music.gain_db", "sound", "음악 크기", "목소리보다 얼마나 작게 재생할지 정합니다. -8 dB는 기준보다 8 dB 작고, -12 dB는 더 작습니다. 말하는 동안에는 자동으로 더 줄입니다.", -40, 0, .5, unit="dB"),
    _select("local_video.text_policy", "output", "화면 설명 글자", "장면 안의 설명 글자를 정합니다. 나레이션 자막은 아래에서 따로 선택합니다.",
            _option("subtitles", "설명 글자 없음"), _option("keywords", "핵심 단어 라벨"), _option("legacy", "기존 방식 유지")),
    _text("local_video.subtitle_languages", "output", "추가 언어", "en,ja,zh,es처럼 입력합니다. 비우면 한국어만 만듭니다."),
    _select("local_video.localized_delivery", "output", "자막·언어별 출력", "설명 글자 없음 모드에서 적용됩니다. 본편을 언어별 영상 또는 한국어 영상과 추가 언어 음성으로 만듭니다. 쇼츠는 모든 언어의 영상으로 만듭니다.",
            _option("video_and_audio", "한국어 본편 + 추가 언어 음성"),
            _option("videos", "자막 없는 언어별 영상"), _option("burned_videos", "자막이 있는 언어별 영상"),
            _option("audio_tracks", "기존 방식 · 영상에 자막 없음 · 음성/자막 파일 따로")),
    _text("promotion.base_url", "output", "홍보 웹사이트 주소", "유튜브 본편·쇼츠 설명에 넣을 주소입니다. 비우면 홍보 링크를 넣지 않습니다."),
    _select("promotion.locale_mode", "output", "업로드 주소 적용 방식", "한국어만 허용하면 다른 언어의 본편·쇼츠 제목과 설명에서 출처를 포함한 웹주소를 제외합니다. 제작자·라이선스 이름은 유지합니다. 언어별 경로는 /en, /ja, /zh, /es를 넣습니다.",
            _option("shared", "모든 언어에서 같은 주소"), _option("language_path", "언어 코드를 경로에 추가"), _option("ko_only", "한국어에만 웹주소 허용")),
    _select("pipeline.output_mode", "output", "생성 범위", "특정 산출물만 필요할 때 변경합니다.",
            _option("all", "전체 생성"), _option("video_only", "영상만"), _option("prompts_only", "프롬프트만"), advanced=True),
    _select("pipeline.variant_mode", "output", "편집본 구성", "보통은 균형본 하나로 충분합니다.",
            _option("four", "네 가지 편집본"), _option("balanced_only", "균형본 하나"), advanced=True),
)

# Detailed fields remain editable, behind one disclosure.
SETTINGS_CATALOG += (
    _select('voice.engine', 'advanced', '음성 엔진', '한국어는 Qwen·Sohee를 사용합니다. Kokoro는 번역 언어용입니다.', _option('qwen3', 'Qwen3-TTS · Sohee'), _option('kokoro', 'Kokoro (번역 언어용)'), advanced=True),
    _text('voice.model_id', 'advanced', '음성 모델', 'MLX-Audio에서 불러올 Hugging Face CustomVoice 모델 ID입니다.', advanced=True),
    _text('voice.model_revision', 'advanced', '모델 리비전', '같은 음성을 재현하기 위해 고정한 40자리 Git 리비전입니다.', advanced=True),
    _select('voice.speaker', 'advanced', '화자', '모든 장면에 사용할 한국어 여성 음색입니다.', _option('Sohee', 'Sohee'), advanced=True),
    _select('voice.language', 'advanced', '합성 언어', '대본을 읽을 언어입니다.', _option('Korean', '한국어'), advanced=True),
    _select('voice.generation_preset', 'advanced', '생성 안정성', '일관성 우선은 보수적인 샘플링 값으로 문장마다 같은 Sohee 톤을 유지합니다.', _option('consistent', '일관성 우선 (권장)'), _option('custom', '고급 샘플링 값 직접 사용'), advanced=True),
    _range('voice.temperature', 'advanced', '샘플링 온도', '고급 샘플링 직접 사용에서 적용되며, 높을수록 음성 토큰 선택이 다양해집니다.', 0.1, 2.0, 0.05, advanced=True),
    _range('voice.top_k', 'advanced', 'Top-K', '고급 샘플링 직접 사용에서 매 단계에 고려할 가능성 높은 음성 토큰 개수입니다.', 1, 200, 1, advanced=True),
    _range('voice.top_p', 'advanced', 'Top-P', '고급 샘플링 직접 사용에서 누적 확률을 기준으로 음성 토큰 후보를 제한합니다.', 0.05, 1.0, 0.05, advanced=True),
    _range('voice.repetition_penalty', 'advanced', '반복 억제', '고급 샘플링 직접 사용에서 같은 소리나 구절이 반복되는 경향을 조정합니다.', 0.5, 2.0, 0.05, advanced=True),
    _select('voice.loudness_mode', 'advanced', '음량 일관성', '문장마다 체감 음량을 맞춥니다. 목소리의 말투는 기본 설정에서 선택합니다.', _option('off', '원본 음량 유지'), _option('leveled', '음량 균일화 (권장)'), advanced=True),
    _range('voice.loudness_target_lufs', 'advanced', '목표 음량', '더 작은 음수일수록 큰 소리입니다. 설명 영상은 -18을 권장합니다.', -30, -12, 1, unit='LUFS', advanced=True),
    _range('voice.loudness_range_lu', 'advanced', '음량 변화 폭', '음량 균일화의 목표 변화 폭입니다. 자연스러운 강약을 남기며 과한 변화를 줄입니다.', 3, 20, 1, unit='LU', advanced=True),
    _range('voice.loudness_true_peak_db', 'advanced', '최대 피크 목표', '음량 보정 단계의 피크 목표입니다. 압축 파일 인코딩 후 실제 피크는 다시 확인해야 합니다.', -6, -0.5, 0.1, unit='dBTP', advanced=True),
    _range('voice.speaking_rate', 'advanced', '최소 말하기 배율', 'Qwen은 이 배율과 목표 속도에 필요한 배율 중 큰 값을 씁니다. 기본 1.0에서는 이미 빠른 발화를 감속하지 않습니다.', 0.8, 1.25, 0.01, unit='배', advanced=True),
    _range('voice.target_syllables_per_second', 'advanced', '목표 말하기 속도', 'Qwen의 목표 발화 길이입니다. 느린 발화는 최대 가속 배율 안에서 맞추며, 이미 빠른 발화를 강제로 감속하지 않습니다.', 4.0, 7.0, 0.1, unit='음절/초', advanced=True),
    _select('voice.pause_mode', 'advanced', '쉼 처리 방식', '종류별 쉼은 쉼표와 대본에 지정한 의미·강조 쉼을 각각 적용합니다.',
            _option('typed', '종류별 쉼'), _option('legacy', '기존 최대 쉼 방식'), advanced=True),
    _range('voice.comma_pause_ms', 'advanced', '쉼표', '쉼표에서 쉬는 길이입니다. 숫자 안의 쉼표는 제외합니다.', 80, 150, 10, unit='ms', advanced=True),
    _range('voice.semantic_pause_ms', 'advanced', '의미 구분 쉼', '대본에서 의미를 구분하도록 지정한 위치에 적용합니다.', 150, 250, 10, unit='ms', advanced=True),
    _range('voice.emphasis_pause_ms', 'advanced', '강조 쉼', '대본에서 강조하도록 지정한 위치에 적용합니다.', 300, 400, 10, unit='ms', advanced=True),
    _range('voice.sentence_pause_ms', 'advanced', '문장 사이 쉼', '문장 끝부터 다음 문장 시작까지의 전체 간격입니다. 말하기 배율과 무관하게 유지합니다.', 400, 600, 10, unit='ms', advanced=True),
    _range('voice.max_internal_pause_ms', 'advanced', '지정하지 않은 최대 쉼', '모델이 구절 안에서 임의로 길게 쉬는 경우의 상한입니다. 지정한 쉼표·의미·강조 쉼에는 적용하지 않습니다.', 50, 800, 10, unit='ms', advanced=True),
    _range('voice.sentence_leading_margin_ms', 'advanced', '문장 앞 안전 여백', '합성 문장 시작 전에 확보할 무음입니다. 문장 사이에는 앞뒤 여백이 함께 적용됩니다.', 0, 300, 10, unit='ms', advanced=True),
    _range('voice.sentence_trailing_margin_ms', 'advanced', '문장 뒤 안전 여백', '문장 끝음 뒤의 호흡입니다. 앞 여백과 합쳐 문장 사이 간격이 됩니다. 쇼츠처럼 빠른 영상은 250ms 안팎을 씁니다.', 200, 1500, 10, unit='ms', advanced=True),
    _range('voice.max_tokens', 'advanced', '최대 음성 토큰', '문장 하나를 합성할 때 허용할 최대 생성 토큰 수입니다.', 1, 32768, 1, unit='개', advanced=True),
    _number('voice.seed', 'advanced', '고정 시드', '모든 문장 생성에 동일하게 재사용하는 0 이상의 정수입니다.', advanced=True),
    _range('voice.min_scene_seconds', 'advanced', '최소 음성 길이', '한 장면 나레이션이 확보해야 할 최소 길이입니다.', 1, 20, 0.05, unit='초', advanced=True),
    _range('voice.max_scene_seconds', 'advanced', '최대 음성 길이', '한 장면 나레이션이 넘지 않아야 할 최대 길이입니다.', 1, 20, 0.05, unit='초', advanced=True),
    _range('music.duck_db', 'advanced', '말할 때 음악 줄이기', '나레이션이 나오는 동안 음악을 추가로 낮춥니다. -13 dB는 평소 음악 크기에서 13 dB 더 낮춥니다.', -40, 0, 0.5, unit='dB', advanced=True),
    _range('music.fade_seconds', 'advanced', '음악 크기 전환 시간', '낮추고 되돌리는 데 걸리는 시간입니다.', 0, 5, 0.1, unit='초', advanced=True),
    _select('music.loop_mode', 'advanced', '배경음악 반복', '영상보다 짧을 때 반복할지 한 번만 재생할지 정합니다.', _option('loop', '반복'), _option('once', '한 번'), advanced=True),
    _range('local_video.scene_gap_seconds', 'advanced', '씬 사이 쉼', '다음 장면의 음성 전에 넣는 쉼입니다. 영상 템포를 고르면 함께 바뀝니다.', 0, 3, 0.05, unit='초', advanced=True),
    _range('local_video.min_scene_seconds', 'advanced', '최소 장면 길이', '음성과 끝 무음을 포함한 로컬 장면의 최소 목표 길이입니다.', 1, 20, 0.05, unit='초', advanced=True),
    _range('local_video.max_scene_seconds', 'advanced', '장면 길이 상한', '로컬 장면이 도달해서는 안 되는 배타적 최대 길이입니다.', 1, 20, 0.05, unit='초', advanced=True),
    _number('render.final_width', 'advanced', '최종 영상 너비', '새 계획에 규격이 없을 때 사용할 최종 가로 픽셀 수입니다.', unit='px', advanced=True),
    _number('render.final_height', 'advanced', '최종 영상 높이', '새 계획에 규격이 없을 때 사용할 최종 세로 픽셀 수입니다.', unit='px', advanced=True),
    _number('render.final_fps', 'advanced', '최종 프레임률', '새 계획에 FPS가 없을 때 사용할 초당 프레임 수입니다.', unit='fps', advanced=True),
    _select('render.x264_preset', 'advanced', 'x264 프리셋', '인코딩 속도와 압축 효율 사이의 균형을 선택합니다.', _option('ultrafast', 'ultrafast'), _option('superfast', 'superfast'), _option('veryfast', 'veryfast'), _option('faster', 'faster'), _option('fast', 'fast'), _option('medium', 'medium'), _option('slow', 'slow'), _option('slower', 'slower'), _option('veryslow', 'veryslow'), _option('placebo', 'placebo'), advanced=True),
    _range('render.x264_crf', 'advanced', 'H.264 화질', '낮을수록 고화질·대용량이 되는 CRF 값입니다.', 0, 51, 1, advanced=True),
    _range('qa.max_undeclared_freeze_seconds', 'advanced', '미선언 정지 허용', '계획에 없는 정지 화면을 허용할 최대 길이입니다.', 0.1, 10, 0.1, unit='초', advanced=True),
    _range('qa.black_frame_amount_percent', 'advanced', '검은 픽셀 비율', '검은 화면으로 판정할 프레임 내 검은 픽셀 비율입니다.', 90, 100, 0.1, unit='%', advanced=True),
    _range('qa.black_frame_threshold', 'advanced', '검은 화면 밝기', '검은 픽셀로 취급할 밝기 임계값입니다.', 0, 255, 1, advanced=True),
    _range('qa.audio_packet_tolerance_seconds', 'advanced', '오디오 끝 오차', 'AAC 패킷 끝부분에 허용할 시간 오차입니다.', 0, 0.5, 0.01, unit='초', advanced=True),
    _range('qa.duration_tolerance_seconds', 'advanced', '길이 메타데이터 오차', '음성 길이 메타데이터에 허용할 시간 오차입니다.', 0, 0.5, 0.01, unit='초', advanced=True),
    _range('voice.max_tempo_factor', 'advanced', '최대 가속 배율', '음성을 목표 길이에 맞출 때 허용하는 가속 상한입니다. 번역 음성에도 적용됩니다.', 1, 1.6, 0.05, unit='배', advanced=True),
    _range('local_video.camera_transition_seconds', 'advanced', '카메라 전환 시간', '새 구도로 이동하는 목표 시간입니다. 개별 카메라 경로에 반영하고 프리뷰에서 확인합니다.', 0, 3, 0.05, unit='초', advanced=True),
    _range('local_video.target_beat_min_seconds', 'advanced', '구도 유지 최소 목표', '시각 비트의 최소 목표 길이입니다. 최소·최대 모두 0이면 길이 조언을 끕니다.', 0, 30, 0.5, unit='초', advanced=True),
    _range('local_video.target_beat_max_seconds', 'advanced', '구도 유지 최대 목표', '나레이션 장면과 별개인 시각 비트의 목표 상한입니다.', 0, 30, 0.5, unit='초', advanced=True),
)


def settings_sections() -> tuple[SectionPresentation, ...]:
    return SETTINGS_SECTIONS


def settings_catalog() -> tuple[SettingPresentation, ...]:
    return SETTINGS_CATALOG


def editable_setting_keys() -> frozenset[str]:
    return frozenset(item.key for item in SETTINGS_CATALOG)


def settings_sections_payload() -> list[dict[str, object]]:
    return [asdict(section) for section in SETTINGS_SECTIONS]


def settings_catalog_payload() -> list[dict[str, object]]:
    return [
        {
            **asdict(item),
            "allow_empty": item.key in {"local_video.subtitle_languages", "music.file", "promotion.base_url"},
            "options": [asdict(option) for option in item.options],
        }
        for item in SETTINGS_CATALOG
    ]


def _model_leaf_keys() -> frozenset[str]:
    payload = HarnessSettings().model_dump(mode="json")
    return frozenset(
        f"{group}.{field}"
        for group, values in payload.items()
        if group not in {"schema_version", "pacing"}
        for field in values
    )


def _validate_catalog() -> None:
    keys = [item.key for item in SETTINGS_CATALOG]
    if len(keys) != len(set(keys)):
        raise RuntimeError("settings catalog contains duplicate keys")
    if frozenset(keys) != _model_leaf_keys():
        raise RuntimeError("settings catalog and HarnessSettings fields differ")

    section_ids = {section.id for section in SETTINGS_SECTIONS}
    for item in SETTINGS_CATALOG:
        if item.section not in section_ids:
            raise RuntimeError(f"unknown settings catalog section: {item.section}")
        if item.control == "select":
            if not item.options or len({option.value for option in item.options}) != len(
                item.options
            ):
                raise RuntimeError(f"invalid select options for {item.key}")
        elif item.options:
            raise RuntimeError(f"non-select setting has options: {item.key}")
        if item.control == "range" and (
            item.step is None
            or item.ui_min is None
            or item.ui_max is None
            or item.ui_min >= item.ui_max
        ):
            raise RuntimeError(f"invalid range metadata for {item.key}")


_validate_catalog()
