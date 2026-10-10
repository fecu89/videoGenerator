# 하네스 구조와 정리 기준

## 제작 흐름

```text
설정 UI → 조사·대본 → 질문 사슬 검사·대본 승인
  → Qwen3-TTS / Kokoro 음성·길이 검사 → translate-scaffold → voice --target-language all
  → 장면 계획·3D 연속성 검사
  → plan-video → 영상 생성대본 승인 → preview → 프리뷰승인(approve-preview)
  → produce --quality draft (기본값) → produce_local → 시퀀스별 초본 렌더 → 초본승인(approve-draft)
      ├─ Blender: MCP 장면 검토 / 백그라운드 Blender 최종 렌더
      └─ Three.js: Playwright Chromium에서 WebGL 렌더
  → FFmpeg 합성 → 실제 프레임·연속성 QA → 저해상도 초본 링크 제공
  → 피드백 반영·최종 제작 요청 → produce --quality final
  → 공통 화면 + 언어별 음성·배경음악 → 언어별 MP4 5개 → 검사·게시·validate
  → 언어별 쇼츠·업로드 문구 → 선택적 로컬 전달 모듈
```

실패한 질문 사슬·연속성·미디어 검사를 우회해 다음 단계로 나가지 않는다.
기존 실행의 계획, 승인 해시, 음성과 완성본은 코드 정리 과정에서 바꾸지 않는다.
초본 요청에서는 `final-draft.mp4`를 먼저 전달하고 결과를 검토한다. 최종본까지
이미 제작 지시를 받았어도 초본 전달을 고해상도 렌더 종료까지 미루지 않는다.

다국어 합성은 게시 전에 수행하고 검사한다. 현재 프로젝트의 `localized_delivery: videos`는
공통 3D 화면을 한 번 렌더하고 한국어·영어·일본어·중국어·스페인어 음성과
배경음악을 각각 결합해 `final-<lang>.mp4` 5개를 만든다. 영상 스트림은 복사하므로
언어마다 3D 렌더를 반복하지 않는다. `burned_videos`를 고르면 각 언어 자막도 넣는다.
`final.mp4`는 한국어 기준 영상으로 유지하며, 완료 화면에서는 각 언어 MP4를 선택해
재생·저장한다. 자막 파일은 CC 업로드와 쇼츠 제작용이고 새 `videos` 출력에는
별도 M4A가 없다. 기존 실행의 `audio_tracks` 설정·승인 해시는 그대로 유지한다.

## 코드의 역할

| 영역 | 구현 | 유지 이유 |
|---|---|---|
| 계획·검사·실행 | `pipeline.py`, `produce_local.py`, `sequence_*.py`, `creative_gates.py` | 승인, 렌더 선택, 캐시, QA, 최종본 게시 |
| Blender 연결 | `blender_backend.py` | localhost:9876 MCP와 네이티브 Blender 실행 |
| Blender 장면 | `blender_renderer/*.py` | Blender 내부 `bpy`로 객체·재질·카메라·키프레임 구성 |
| Three.js 장면 | `science_renderer/src/` | 브라우저의 WebGL로 3D 렌더 |
| 물리 계산 | `*_math.py`, `spectra.py`, `simulation.py` 등 | 좌표·스펙트럼 계산, 입력 계약·사실성 검증 |
| 음성 | `voice.py`, `mlx_voice.py`, `voice_audio.py` | 엔진별 합성과 공통 음성 처리 |
| 합성 | `media.py`, `sequence_transitions.py` | FFmpeg 인코딩·편집 전환·음성 합성 |
| 과거 실행 호환 | `render.py`, `production_render.py`, `shot_backends.py` | Three.js·FFmpeg를 호출하는 이전 계획과 검토 경로 |
| 화면 글자 | `text_labels.py`, `blender_renderer/callout.py`, `callout_math.py`, `science_renderer/src/callout.ts` | 계획이 소유한 핵심 단어 라벨과 지시선, text 게이트 |
| 단계 승인 | `preview.py`, `stage_approvals.py` | 대표 프레임 프리뷰와 프리뷰·초본 승인 해시 |
| 다국어 자막 | `language_voices.py`, `translations.py`, `kokoro_voice.py`, `localize_voice.py`, `subtitles.py`, `localize.py` | 언어별 엔진·번역 예산·장면 맞춤 음성·문장 타이밍 자막·언어별 완성본 조립 |
| 쇼츠·업로드 | `shorts.py`, `upload_text.py` | 최종 영상에서 핵심 장면만 남긴 언어별 세로 쇼츠, 언어별 제목·설명과 출처 표기(`upload.md`, 완성 화면) |

지원 3D 엔진은 **Blender와 Three.js**다. 새 3D 장면은 Blender MCP를 우선
사용하되 Three.js도 허용한다. 계획에 렌더러를 명시하고 시퀀스별 혼합을
허용한다. 기존 계획에서 생략된 렌더러는 이전과 같이 Three.js다.
잘못된 엔진 이름은 오류로 중단하며 다른 엔진으로 자동 전환하지 않는다.

현재 독립적인 Python 3D 래스터 렌더러는 없다. `bpy` 코드, 물리 계산,
FFmpeg 호출을 Python 파일이라는 이유로 지우면 Blender 제작과 QA도 깨진다.
새 Python 3D 대체 경로는 추가하지 않는다. 흑체복사의 `blackbody_worker.py`도
`bpy`를 사용하는 Blender 전용 진입점이며 독립 Python 렌더러가 아니다.

한국어는 Qwen3-TTS, 번역은 Qwen·Kokoro를 사용한다. 인코딩·음량·원자적 게시·
메모리 수명은 `voice_audio.py`를 공유한다. 새 설정 schema-v5에서는 Vox 엔진과
전용 필드를 제거했다. `archived_voice_settings.py`는 schema-v3/v4 기록을 읽고
원래 해시를 유지하는 호환 자료형이다. Qwen 재합성은 계속 지원하지만 과거 Vox
실행의 합성은 차단한다. 사용자가 명시적으로 현재 설정으로 갱신한 경우에만
Qwen으로 다시 생성한다. 과거 실행 파일과 승인 해시를 자동 수정하지 않는다.
이전 렌더 명령의 최종본 직접 공개는 차단되어 있다. 새 제작은 schema-v2 계획과
`produce`를 사용한다.

## 장면 사이의 연속 동작

영상 계획과 구현은 [대상을 이어가는 전환](continuous-transitions.md)을 기본으로
한다. 앞 장면의 전체를 확대해 내부를 드러내거나, 한 단위를 유지한 채 주변
단위를 집결시키거나, 기존 대상이 빠지는 동안 다음 대상을 진입시킨다.

| 단계 | 연속성을 유지하는 책임 |
| --- | --- |
| 계획 프롬프트·시퀀스 계획 | 추적 객체, 전환 구간, 시작·종료 상태와 글자 영역을 기존 검토 필드에 기록한다. 연결된 비트를 같은 시퀀스로 묶고 모든 경계를 `continuity-plan.json`에 선언한다. |
| Blender·Three.js 장면 | 같은 객체와 좌표계에서 공통 canonical frame으로 상태를 평가한다. 나레이션 씬 변경으로 장면 그래프나 시간을 초기화하지 않는다. |
| 렌더 상태 캡처·creative 게이트 | 실제 객체·카메라의 경계 상태와 선언된 방향을 검사한다. 시퀀스를 나눌 때도 앞뒤 상태를 이어받는다. |
| 시각 검토·전달 | 실제 전환의 전·중·후 화면에서 가림·잘림·연결선·글자를 검토하고, QA를 통과한 음성 포함 저해상도 초본을 먼저 전달한다. |

`bonding-flow-blender-v2`의 [구현](../blender_renderer/bonding_flow.py)은 객체를
한 번 구성하고 `sample(frame)`에서 공통 시간으로 평가하며 `bake()`로 편집용
키프레임을 저장하는 예다. 이 그래프의 10개 장면 계약은 해당 영상 전용이다.
다른 주제에는 연결 원칙을 적용하고 필요한 모형과 동작을 구현한다.
FFmpeg 편집 전환은 별도의 효과이며 객체의 연속 동작을 대신하지 않는다.
자동 검사는 선언된 경계와 방향을 다루므로 실제 영상의 시각·내용 검토도 필요하다.

## 설치 파일과 캐시

### 모델별 메모리 수명

- 모델 실행부는 `RuntimeBindings.release_unused_memory`에 해당 장치의 정리
  함수를 제공한다. 공통 음성 처리부는 문장이 끝나거나 실패할 때 호출한다.
- Qwen은 문장 종료 후 MLX 동기화·가비지 수집·`mx.clear_cache()`를 실행한다.
  `close()`에서 모델 참조를 먼저 해제하며 실패 경로에서도 같은 규칙을 지킨다.
- `generate_audio`가 직접 만든 합성기는 성공·실패 모두 `finally`에서 닫는다.
  `close()`는 모델의 보유 참조를 해제한 뒤 장치 캐시를 정리한다.
  사용 중인 모델의 가중치 자체를 줄이거나 정밀도·목소리 설정을 바꾸지 않는다.
- 여러 장면을 나눠 처리하려고 합성기를 외부에서 주입하면 호출자가 소유한다.
  `with create_synthesizer(settings.voice) as synth:` 안에서 재사용하고, 전체
  작업을 마칠 때 닫는다.
- 정리 실패는 경고로 기록하며 원래의 추론·인코딩 오류를 덮어쓰지 않는다.
  음성 모델을 종료한 뒤 음성 인식 등 다음 모델을 실행해 메모리 중첩을 피한다.
  새 모델을 추가할 때도 장치별 정리 함수와 명시적인 종료 경계를 구현한다.

### 대본 연기

Qwen은 `instructions_file`의 Sohee 톤 지시에 승인된 문장별 감정 지시를 더한다.
`emotion_mode=off`이면 전체 톤만 적용한다. `script_only`에서는 모든 문장의
지시를 요구하며 실제 지시를 생성 보고서에 남긴다. [작성·검토 절차](voice-acting.md)를 따른다.

### 설치 캐시

- `.render-tools/playwright`는 임시로 프로젝트 안에 설치했던 Chromium 및
  Playwright용 FFmpeg 바이너리다. 하네스 소스가 아니므로 Git에서 제거했다.
- 이 컴퓨터의 바이너리는 `~/Library/Caches/ms-playwright`로 옮겼다.
  Playwright가 기본 위치에서 찾으므로 프로젝트별 경로 설정이 필요 없다.
- Three.js와 실제 브라우저 UI 테스트는 Chromium이 필요하다. 설치 명령은
  `science_renderer`에서 `npm ci` 후 `npx playwright install chromium --only-shell`이다.
- Blender만 렌더하면 Chromium은 필요 없다. 합성용 시스템 `ffmpeg`·`ffprobe`는
  여전히 필요하며 Playwright가 제공하는 FFmpeg와 별개다.
- `node_modules`, 브라우저 캐시, 렌더 캐시와 `tmp`는 재생성 가능한 설치·작업
  산출물이다. 원본 PDF, 대본, 사용자 설정, `runs`의 완성본과 음성은 삭제하지 않는다.

## 이번 정리

- 프로젝트 내부 브라우저 바이너리 25개(약 199MB)를 표준 캐시로 이동하고
  `.render-tools/`를 Git 제외 대상으로 지정했다. 디스크에서 브라우저를 삭제한 것은 아니다.
- `tmp/pdfs/apparent-motion`의 이전 MLX 음성 생성 스크립트
  `voice_full_cycle.py`, `voice_full_cycle_retry.py`, `resume_voice.py`를 제거했다.
  해당 역할은 공통 `voice` 명령이 담당한다.
- 유지하는 임시 음성 검토 스크립트 2개의 삭제된 `mlx_voice` 참조를
  공통 `voice_audio`로 바꿨다.
- CLI 사용법의 중복 명령 목록을 없애 등록된 명령에서 생성한다. 누락됐던
  `blender` 명령도 표시한다.
- 지원하지 않는 렌더러의 묵시적 Three.js 전환을 제거했다.
- Blender/Three.js 구현과 기존 실행 호환 코드는 호출 관계를 확인해 유지했다.


## 최소 설정 화면과 프리뷰 상수

`settings_catalog.py`는 기본 항목과 접힌 고급 옵션을 구분한다.
`pacing_presets.py`의 템포와 `output_profiles.py`의 영상 규격을 포함해 기본 11개를
보이며, 생성 범위·편집본은 추가 출력 옵션에 둔다. 나머지 모델·음량·템포·렌더·QA
43개는 고급 옵션에 모아 둔다. 프리뷰 상수와 프리셋 메타데이터 외의 모든 모델 필드는
카탈로그에서 한 번씩 노출되고 기본·고급 화면의 값은 서로 동기화된다.

schema-v6의 `RenderSettings`는 최종 출력 크기·FPS와 인코딩 설정만 직렬화한다.
프리뷰 크기는 고정 긴 변 384px에서 출력 비율로 계산하고, 9fps·검사 간격 0.5초·
접촉 시트 8열은 `runtime_defaults.py`를 따른다. schema-v1~v5는
`ArchivedRenderSettings`로 과거 값을 읽어 스냅샷과 승인 해시를 보존한다.

## 업로드 홍보 설정

`PromotionSettings`는 주소와 언어별 경로 방식을 검증하고 주소를 조합한다.
프로젝트 설정 로딩은 공용 파일 위에 같은 폴더의 `settings.local.json` 홍보 값만
적용한다. 설정 UI 저장은 공용 파일의 홍보 값을 기본값으로 두고 개인 값을
로컬 파일에 분리한다. 새 실행 스냅샷에는 합쳐진 값을 저장한다. 기존 실행은
개인 설정을 읽지 않으며, 홍보 설정이 없던 실행의 해시는 그대로 유지한다.
`upload_text.py`는 실행 스냅샷으로부터 언어별 링크를 얻어 영상·쇼츠 설명에
추가한다. 승인 후에는 `upload-overrides.json`의 검증된 `promotion` 값으로
업로드 정책만 바꿀 수 있으며 렌더 설정 해시는 유지한다. `ko_only`는 한국어
외 본편·쇼츠 제목과 설명에서 모든 웹주소를 제외하고 제작자·라이선스 이름은
유지한다. `upload.md`, 완료 웹, 로컬 업로더가 같은 설명을 사용한다.

## 선택적 로컬 업로드 모듈

공개 하네스의 `delivery.py`는 `.local-integrations/delivery.py`를 별도 프로세스로
호출하는 연결부다. 제공자별 업로드 구현·의존성·설정·인증·재개 기록은 이 Git 제외
폴더에 둔다. 모듈이 없는 설치에서는 최종 제작을 정상 완료하고 전달을 건너뛴다.

`produce --quality final`은 최종 검사·게시, 쇼츠와 업로드 문구 생성에 모두 성공한
뒤에만 연결부를 호출한다. 초본·프롬프트 전용 제작에는 호출하지 않는다. 전달 실패는
이미 검증된 영상을 되돌리지 않으며 명령의 종료 코드와 별도 `delivery-report.json`에
표시한다. 완료 화면은 로컬 영상과 외부 업로드 결과를 구분한다.

모듈 계약: 현재 Python으로 `--action upload|plan|authorize`, 선택적인 `--run-dir`,
`--automatic`, `--profile`을 전달한다. 셸을 거치지 않으며 비밀값을 명령행에 넣지 않는다.
성공은 종료 코드 0, 실패는 0이 아닌 값이다. 실행 폴더의 보고서에는 `status`, `error`,
`items`(언어·종류·상태·공개 HTTPS URL)를 기록할 수 있다. 토큰·세션 URI는 보고서에
넣지 않는다. 공개 저장소에는 이 계약·연결부·일반 테스트만 포함한다.

로컬 구현은 단일 채널 모드를 선택할 수 있다. 이 모드는 한국어 본편 1개와
언어별 쇼츠를 기본 채널에 올리고 본편의 번역 제목·설명은 `localizations`에
포함한다. 추가 음성은 공개 Data API로 업로드할 수 없어 별도 Studio 작업으로
넘긴다. 완성 MP4의 배경음악 포함 오디오를 추출하고 대상 영상·채널·해시가 든
`studio-audio-job.json`을 만든다. `api_status: complete`와
`status: awaiting_studio_audio`를 구분하며 완료 웹에도 추가 음성 게시 대기를
표시한다. 에이전트의 브라우저 검증은 별도 실행이 필요하다.

```bash
python -m video_harness deliver runs/<run> --plan
python -m video_harness deliver --authorize --profile <profile>
python -m video_harness deliver runs/<run>
```

첫 명령은 전달 계획 확인, 두 번째는 개인 모듈 인증, 세 번째는 완성 산출물의 전달
재시도다. 제공자별 설명은 로컬 모듈의 README를 따른다. 개인 모듈을 Git에 올리지
않으면 다른 컴퓨터로 복제할 때 별도로 옮겨야 한다.
