# Video Generator Agent Harness

이 폴더의 작업은 Codex가 편집 판단과 샷 설계를 맡고 Python이 검증, 음성 생성,
샷 컴파일, 결정론적 렌더와 합본을 수행하는 제작 흐름이다. 새 실행의 전체
대본은 항상 사람이 피드백하고 명시적으로 승인해야 한다. 음성 뒤에 만든
영상 생성대본도 사람이 별도로 검토하고 승인해야 하며, 그 전에는 렌더링으로
넘어가지 않는다.

## 공통 연출 기준

대본과 영상 계획을 작성하거나 수정하기 전에
`video_harness/agent/DIRECTION.md`를 읽는다. 사용자 피드백에서 확정한 기본
연출을 모든 제작 단계에 적용하며, 현재 작업의 명시적 지시를 우선한다.
대본 단계에서는 질문 사슬과 밝은 첫 전달을, 화면 단계에서는 큰 이미지·수식,
대상과 글자의 영역 분리, 배경판·하단 보조 문구 제거를 확인한다.

## 0. 설정 확인

새 실행을 시작하기 전에 `videoGenerator/settings.md`를 읽고 설정 화면을 연다.

```bash
python -m video_harness settings-ui
```

사용자가 브라우저에서 값을 확인하고 **저장 후 닫기**를 누르면 서버가 종료된다.
그 다음 아래 명령으로 effective settings를 확인한다.

```bash
python -m video_harness settings [run]
```

아직 실행 폴더가 없으면 `[run]`을 빼고 실행한다. 기존 실행이면
`runs/<run>`을 지정해 `run-settings.json` 스냅샷을 읽는다. 프로젝트 기본값은
루트 `settings.json` 하나뿐이며 구현 상수를 직접 고치지 않는다. 기존 실행에
변경을 의도적으로 적용할 때만 사용자의 명시적 요청을 받은 뒤
`--refresh-settings`를 사용한다.
프롬프트, 길이 보정, 새 계획의 기본 렌더 값, QA와 공개 단계는 이 resolved
settings를 따른다. 영상 템포, Qwen·Sohee의 말투, 음악과 출력 방식을 확인한다.
모델은 Hugging Face의 고정 리비전으로 불러온다. 설정과 설치는 `settings.md`를 따른다.

## 절대 규칙

- 로컬 음성 합성은 편집상 확정된 대본에만 사용한다. 조사, 대본 작성, 편집 같은 LLM 판단은 현재 Codex 대화에서 수행한다.
- 조사자료에 없는 사실이나 출처를 만들지 않는다.
- 조사와 전체 대본 초안을 만든 뒤 `story-ui` 웹에서 사람의 피드백을 받고,
  현재 전체 대본을 사람이 명시적으로 승인한 뒤에만 음성부터 진행한다.
- 설정 승인, 이전의 일반적인 진행 허가, 침묵은 현재 대본의 승인이 아니다.
- 승인 뒤 대본이 조금이라도 바뀌면 변경된 전체 대본을 다시 제시하고 새로 승인받는다.
- 스토리 웹에서 영상 아이디어(선택)를 함께 받는다. 없으면 대본에 맞게 연출을 정한다.
- 대본 승인·음성 검증 뒤 영상대본 작성 → 계획 검증 → 프리뷰 렌더 → 검토 웹까지 중간 영상대본 승인 없이 진행한다. 프리뷰·초본 승인은 유지한다.
- Python 코드로 나레이션을 자동 작성하거나 수정하지 않는다.
- 모든 최종 음성은 effective settings의 `voice.min_scene_seconds` 이상
  `voice.max_scene_seconds` 이하여야 한다(내장 예시: 5.0~14.0초).
- 유효하지 않은 음성이 하나라도 있으면 영상 제작 계획 단계로 넘어가지 않는다.
- `script.json`의 씬 번호, 제목, 나레이션을 모든 후속 산출물의 기준으로 사용한다.
- `production-plan.json`이 존재하면 영상 제작 정보의 기준은 이 파일이며, `video-plan.md`는 파생 검토본이다.
- 새 실행은 `variant-plan.json`으로 네 편집 레시피 계약을 만들고, materialize할
  출력 수는 effective settings의 `pipeline.variant_mode`를 따른다. 파일이 없는
  기존 실행만 단일 최종본 호환 경로를 사용한다.
- 정확한 과학 관계를 생성형 영상 모델에 맡기지 않는다.
- 성능 조사는 `video_harness/docs/render-performance.md`의 임시-root 절차를
  따른다. `render-performance.json`의 effective `backend.actual` attestation을
  확인한다. Metal이 migration cross-backend visual gate를 통과하지 못했으므로
  production 기본값은 SwiftShader로 유지하며, SwiftShader가 cross-backend 비교를
  통과했다는 뜻은 아니다. 명시적 Metal job은 `backend.actual=metal`일 때만 인정한다. same-backend exact determinism
  cache gate와 SSIM/PSNR cross-backend QA를 섞지 않는다. concat normalization
  fallback도 concat phase event의 `mode`/`normalized_inputs`로 명시적으로 남긴다.

## 1. 입력과 실행 폴더

사용자는 주제 또는 PDF를 제공한다. 실행마다 `runs/<YYYYMMDD-HHMMSS>-<topic-slug>/`를 만들고 다음 구조를 유지한다.

```text
input/
research.md
script.json
story-review.md
duration-report.json
voice-generation-report.json
production-plan.json
local-sequence-plan.json
online-plan.json
variant-plan.json
video-plan.md
video-plan-approval.json
run-settings.json
pipeline-report.json
audioFiles/
videoFiles/
  prompts/
    local/
    online/
  sequences/
  onlineReferences/
  previews/half-second/
  variants/
local-production-report.json
```

새 schema-v2 실행은 루트 `videoPrompt/`를 만들지 않는다. 이 디렉터리는
schema-v1 호환 실행에서만 사용한다.

PDF 입력은 원문과 페이지의 표, 도표, 사진, 배치를 함께 검토한다. PDF를 주 자료로 사용하고 중요한 사실의 확인이나 의미 있는 공백에만 웹 조사를 추가한다. 주제 입력은 신뢰할 수 있는 최신 자료를 웹에서 조사한다.

사용자가 대본을 저장하거나 고쳤다고 알리면 파일을 다시 읽고 제작 사본을
남긴다. 시각 수정만 요청한 기존 실행은 확정된 나레이션·음성·길이를 재사용한다.

## 2. 조사

1. `video_harness/agent/prompts/story.md`를 처음부터 끝까지 읽는다.
2. 여러 출처의 핵심 사실과 충돌 여부를 확인한다.
3. 출처마다 `S1`, `S2`처럼 안정적인 ID를 부여한다.
4. `research.md`에 조사 요약, 시각 자료 관찰, 핵심 사실, 불확실한 주장, 사람이 열 수 있는 출처 링크를 작성한다.
5. 숫자, 인과관계, 역사, 기술 원리, 최상급 표현은 근거를 별도로 확인한다.

## 3. 주제 선정과 대본

1. 의외성, 시각화 가능성, 인과관계의 선명도, 근거 신뢰도를 각각 1~5점으로 평가한 후보를 만든다.
2. 가장 강한 후보 하나를 선택한다.
3. `video_harness/schemas/script.schema.json`을 따라 `script.json`을 작성한다.
4. 씬은 하나의 질문, 답, 또는 시각적 사건만 담는다.
5. 씬 제목은 파일명에 쓸 수 있도록 짧게 작성한다.
6. 나레이션은 effective settings의 `voice.min_scene_seconds`~`voice.max_scene_seconds`를 목표로 하지만(내장 예시: 5.0~14.0초), 실제 음성 측정 전에는 `duration_seconds`, `audio_file`, `video_prompt_file`을 `null`로 둔다.
7. 각 사실 기반 씬의 `source_ids`에 근거 출처를 연결한다.
8. 로컬 모델 검증을 실행한다.

```bash
/opt/homebrew/opt/python@3.13/libexec/bin/python3 -c "from pathlib import Path; from video_harness.models import ScriptArtifact; ScriptArtifact.model_validate_json(Path('runs/<run>/script.json').read_text()); print('script.json OK')"
```

## 4. 대본 확정 경계

`voice.pause_mode=typed`에서는 쉼표·문장 끝의 쉼을 자동 적용한다. 의미 구분과
강조가 필요한 위치는 [종류별 쉼](../docs/voice-acting.md#종류별-쉼)의
`sentence_pauses`에 문장 번호·구절·종류로 지정한다. 읽을 본문에는 쉼 지시를
삽입하지 않는다. 이는 감정 연기와 별개이며 대본 웹에 지정 위치를 함께 보여준다.
사용자가 쉼 위치를 고치면 메타데이터를 반영하고 새 음성의 자연스러움을 확인한다.

전체 대본의 [문장별 연기](../docs/voice-acting.md)는 effective settings로 결정한다.
`voice.emotion_mode=off`이면 `sentence_delivery`를 생략하거나 `[]`로 두고,
승인용 대화·`story-review.md`에는 읽을 대사만 제시한다. `[호기심 · 중간]` 같은
감정·강도 표기나 별도의 문장별 연기 표를 만들지 않는다. “검토용”이라는 이유로
적용되지 않는 연기를 붙이지 않는다. 선택된 전체 말투는 별도로 유지한다.
`script_only`일 때만 `sentence_delivery`로 모든 문장의 감정·강도를 지정하고
승인용 대화·검토본에 한국어 연기 지시를 함께 표시한다.
문장을 바꾸지 않고 연기만 수정하는 요청은 요청 범위의 연기를 바꾸어 짧은 비교
샘플부터 검토한다. 과거 승인 대본의 연기 메타데이터는 설정을 읽었다는 이유로
삭제하지 않으며, 대본 재작성 요청에서는 현재 설정을 따라 새 대본을 작성한다.

`story-review.md`에는 후보별 점수와 선정 이유, 스토리 엔진, 전체 씬
번호·제목·나레이션, 주요 출처, 남은 팩트체크를 사람이 읽기 좋은 형태로 쓴다.

`python -m video_harness story-ui runs/<run>`으로 현재 전체 대본과 스토리 문서를 웹에 연다. 같은 화면에서 장면별 수정 의견과 영상 아이디어(선택)를 받는다. 최초 대화에서 받은 아이디어도 `story-feedback.json`의 `visual_brief`와 함께 참고한다. 아이디어가 비어 있으면 추가 질문 없이 대본에 맞춰 연출을 정한다.

- 웹의 **대본 승인** 또는 대화의 명시적 대본 승인 후에만 음성 단계로 이동한다. 웹 승인은 `story-approval.json`의 script 해시가 현재와 같은지 확인한다.
- **수정 의견 저장**은 승인이 아니다. `story-feedback.json`의 장면별 `comments`와 `overall`을 읽어 `script.json`·`story-review.md`를 고치고 웹을 새로 제시한다.
- `visual_brief`는 선택 연출 방향이며 대본 수정 의견이 없어도 입력할 수 있다. 빈 값도 승인 가능하다.
- 수정 후 새 버전에서는 이전 장면별 의견을 새 요청으로 재전송하지 않는다. 웹이 기존 아이디어만 유지하고 의견 입력을 비우며, 다음 저장 때 이전 기록을 `review-history/`에 보존한다. 에이전트는 이전 의견이 실제로 반영되었는지 확인한다.
- 서버를 실행한 채 사용자 입력을 기다린다. 승인하거나 프리뷰 재생성을 요청하면 기록을 쓴 뒤 화면과 서버가 닫히고, 저장만 하면 열린 채로 남는다. 재생성한 프리뷰는 `preview-ui`로 다시 연다. 저장/승인 후 해당 JSON을 읽고 다음 단계를 이어간다. 웹은 에이전트 없이 자체적으로 대본이나 코드를 생성하지 않는다.
- 중단하면 후속 제작을 하지 않는다.

승인 뒤에도 다음 경우에는 자동 진행을 멈춘다.

- 길이 보정이 대본의 의미를 바꾼다.
- 해결되지 않은 사실이나 출처가 씬의 의미를 바꾼다.
- 필수 자격 증명, 외부 생성 클립, 참조 자산이 없다.
- 검증 실패를 안전하게 고칠 수 없다.
- 요청 범위를 바꾸는 새로운 창작 선택이 필요하다.

## 5. 음성 생성

사람의 명시적 대본 승인 경계를 통과하면 실행한다.

`video_harness.voice`는 한국어를 Qwen3-TTS로 번호순 직렬 합성한다.
Sohee 톤 프리셋·토큰 예산·목표 속도·최소 배율 검사를 사용한다.
완전한 문장만 나누며 대본을 임의로 바꾸지 않는다. 문장 앞뒤 여백은 배속과 무관하다.
목표 속도에서 계산한 배율과 `speaking_rate` 중 큰 값을 적용하므로, 기본 최소
배율 1.0에서는 이미 빠른 발화를 감속하지 않는다. `max_tempo_factor` 초과는
재시도 후 실패한다. 내부 무음 상한과 전체 씬 길이 검사는 유지한다.
전체 예상 길이가 씬 최대 길이의 97.5%를 넘거나 후보가 모두 실패하면 게시하지 않는다.
모든 선택 씬의 길이가 유효할 때만 MP3,
sidecar, 대본, 길이 보고서, `voice-generation-report.json`을 한 트랜잭션으로
게시한다. 생성된 각 MP3 옆에는 같은 이름의 `.txt` 대본 파일을 원본 나레이션
그대로 남긴다.

전체 씬 최초 생성:

```bash
python -m video_harness voice runs/<run>/script.json
```

특정 씬 재생성:

```bash
python -m video_harness voice runs/<run>/script.json --scenes 2,5,7 --force
```

음성 생성기는 `duration-report.json`을 만들고 `script.json`의 음성 경로와
실측 길이를 갱신한다. output mode와 무관하게 모든 씬의 TTS와 길이 검증을
완료한다. 씬은 모델을 한 번 로드한 프로세스에서 번호순으로 합성하며 에이전트나
Python 스레드 풀에 나누지 않는다. schema-v1 원격 TTS와 schema-v2 Apple TTS
설정 실행은 기존 MP3 검증·렌더만 허용하고, 재합성 전에
`settings <run> --refresh-settings`로 현재 schema-v6를 명시적으로 채택한다. schema-v3 Qwen 실행은 기존 스냅샷으로 재합성할 수 있다.

## 6. 길이 보정

`duration-report.json`에서 범위를 벗어난 씬만 고친다.

- `voice.min_scene_seconds` 미만: 같은 시각적 사건 안에서 출처로 뒷받침되는 구체적 설명을 추가한다.
- `voice.max_scene_seconds` 초과: 의미를 잃지 않도록 먼저 문장을 줄인다.
- 한 사건이 현재 최대 길이 안에 들어갈 수 없을 때만 두 씬으로 나누고 이후 씬 번호를 연속되게 다시 매긴다.
- 같은 사건을 다룬 인접 씬만 병합할 수 있다.

나레이션을 수정한 씬은 `duration_seconds`와 `audio_file`을 `null`로 되돌리고 해당 씬만 `--force`로 다시 생성한다. 모든 씬이 effective settings의 현재 길이 범위에 들어갈 때까지 반복한다. 스토리 의미가 달라지는 수정은 사용자에게 다시 확인한다.

## 6-1. 번역과 언어별 음성

`text_policy: subtitles`이고 `local_video.subtitle_languages`가 있는 실행은
한국어 음성 확정 뒤, 영상 계획 전에 언어별 음성을 만든다.

```bash
python -m video_harness translate-scaffold runs/<run>
```

`translations.json` 틀이 장면마다 `budget_seconds`(한국어 `duration_seconds`)와
빈 `text` 항목을 담는다. 에이전트는 각 언어 문장을 채운다. 같은 파일의
`title`·`shorts_title`·`description`에는 영상 제목·쇼츠 제목(`script.json`의
`shorts_title`)·유튜브 설명(`upload_description`)의 언어별 번역을 채운다. 대본에
쇼츠 제목이나 설명이 있는데 번역이 비어 있으면 `translation-gate`가 거부한다. 문장은 마침표·물음표
등으로 끝나야 하고, 예상 길이(글자 수 ÷ `language-voices.json`의
`units_per_second`)가 예산의 1.25배를 넘으면 `translation-gate`가 거부한다.
게이트는 추정일 뿐이고, 실제 합성 길이는 문장 여백(문장마다 앞뒤 여백의 합, 현재 약 0.3초)과 모델 속도로
정해진다. 번역은 예상 길이가 예산의 약 0.9배 이하가 되도록 쓴다. 합성에서
`scene_too_long`·`duration_over_target`이 나오면 그 장면·언어만 줄이고
`--scenes`로 다시 합성한다. 기본 속도값은 2026-09-24 실측(ja 약 4.8, zh 약 4.3
단위/초)에 맞춰 ja 5.0, zh 4.2다.

```bash
python -m video_harness voice runs/<run>/script.json --target-language all
```

언어마다 `language-voices.json`의 엔진(영·일·스페인어 Kokoro, 중국어 Qwen3-TTS)을
로드해 `audioFiles/<lang>/`와 `voice-generation-report-<lang>.json`을 만들고
`translation-fit-gate-<lang>.json`을 쓴다. 장면은 한국어 장면 길이에 맞춰
단일 배율(≤1.25)로 보정되고, 짧으면 타임라인 무음이 채운다. 넘치는 장면은
`scene_too_long`으로 실패하며 그 언어 번역을 줄여 `--target-language <lang>
--scenes N --force`로 다시 만든다. 한국어 마스터 파일은 바뀌지 않는다. 다른
언어 음성은 존재·길이·무음·클리핑만 자동 검사하며 청취 검토는 한국어만 한다.

초본·최종 제작의 다국어 산출물은 `local_video.localized_delivery`에 따른다.
현재 프로젝트 기본값 `videos`는 공통 `video-only` 영상에 언어별 음성·배경음악을
합쳐 자막 없는 `final-draft-<lang>.mp4`, `final-<lang>.mp4`를 만든다.
한국어와 추가 언어 en,ja,zh,es를 선택하면 각 언어 MP4 5개를 전달하며 별도 M4A는
만들지 않는다. `burned_videos`는 같은 언어별 영상에 해당 언어 자막을 번인한다.
`audio_tracks`는 과거 실행용 영상 하나와 별도 M4A 출력 호환 경로다.
`final.mp4`는 한국어 기준 영상으로 유지한다. `subtitles/<lang>.ass|.srt`는
CC 업로드·쇼츠 제작에 사용하며 쇼츠에는 언어별 자막을 번인한다.
`subtitle-gate-<lang>.json`, `localization-<quality>-gate.json`으로 자막 형식과
모든 언어 영상의 화면 크기·프레임 수·길이·음성 존재를 검사한다.

## 7. schema-v2 시퀀스 영상 제작 계획

모든 음성이 유효해진 뒤 `video_harness/agent/prompts/video.md`를 처음부터 끝까지 읽는다.

`script.json`은 확정된 나레이션과 음성의 기준으로 유지한다. 공통 시각
계획은 schema-v2 `production-plan.json`, 결정론적 연속 실행은
`local-sequence-plan.json`, 온라인 생성 대안은 `online-plan.json`, 네 편집
레시피 계약은 schema-v2 `variant-plan.json`에 작성한다.

각 공통 비트는 프롬프트를 쓰기 전에 로컬 또는 온라인 경로로 라우팅한다.

[연속 전환 규칙](../docs/continuous-transitions.md)에 따라 앞 장면의 무엇을
따라 다음 설명으로 들어가는지 먼저 정한다. 전체→내부 확대, 단위→집합의
집결, 구성 요소의 분리·재결합, 기존 대상의 퇴장과 새 대상의 진입을 계획한다.
추적 객체 ID, 전환 시작·끝 프레임과 위치·크기를 기존 검토 필드에 명시하고,
화면 글자는 `labels`로 선언한다. 비트를 나누어도 객체와 공통 시간은 이어가며, 연속된 비트는 가능한
한 같은 `visual_sequence`에 둔다. 모든 경계는 `continuity-plan.json`에 기록하고
실제 전환의 전·중·후 프레임과 자동 검사를 함께 확인한다.

- `local`: 궤도, 시선, 투영, 식현상, 가림처럼 프레임마다 계산되는 관계를
  하나의 연속 시퀀스로 렌더한다.
- `online_required`: 로컬 기준 영상을 V2V 참조로 사용하거나 정확한 다중 객체
  계산이 필요 없는 생성 장면을 독립 온라인 샷으로 만든다.

정확한 관계의 owner는 `simulation`, `deterministic_overlay`, `reference_frame` 가운데 하나여야 한다. 생성 모델이 궤도, 시선선, 투영점, 가림 정렬을 소유하게 하지 않는다.

한 씬 안에서도 관측 규모나 설명 초점이 바뀌면 서로 다른 비트로 분리한다.
전체 정렬과 국소 현상을 한 샷에 욱여넣지 않는다. 예를 들어 일식은
`태양-달-지구의 전체 위치`를 먼저 보여준 뒤 `지구를 확대해 달 그림자가
표면을 지나가는 모습`을 별도 비트로 보여준다. 월식은 `태양-지구-달의 전체
위치` 다음에 `달을 확대해 지구 그림자 안으로 들어가는 모습`을 별도 비트로
보여준다.

로컬 시퀀스는 계획이 소유한 canonical FPS(새 계획의 내장 예시: 30fps) 반열림 프레임 범위, 씬별 오디오 범위와 effective `local_video.scene_gap_seconds` 끝 무음,
컨트롤러 우선순위, 단조로운 시뮬레이션 시간을 명시한다. 온라인 계획은 모든
공통 비트를 8초 이하 샷으로 덮고, 정밀 관계에는 로컬 V2V 참조를 둔다. 끝
무음 동안 로컬 시뮬레이션은 계속 진행하며 최종 합본에 딥투블랙을 추가하지 않는다.

네 계획을 작성한 뒤 대본/계획 해시, 씬·비트·시퀀스 순서, 프레임 범위,
온라인 커버리지와 참조 경로를 검증한다.

`production-plan.json`은 `balanced` 기본 타임라인이다. `variant-plan.json`은 같은 음성과 씬 순서를 공유하는 네 레시피를 선언한다. `pipeline.variant_mode`는 이 계약을 바꾸지 않고 최종 공개 때 어떤 레시피를 materialize할지만 정한다.

- `balanced`: 기본 계획과 정확히 같은 루트 최종본
- `explain`: 원리와 관계를 더 명확하게 보여주는 대안
- `dynamic`: 가까운 구도와 더 강한 움직임을 사용하는 대안
- `cinematic`: 조명과 화면 여백을 정돈한 대안

레시피를 무작위로 만들지 않는다. 변형은 카메라, 레이어 타이밍, 조명,
표시 크기만 바꾸며 물리 상태와 시뮬레이션 시간은 바꾸지 않는다. 바뀌지 않은
시퀀스 마스터는 재사용한다.

```bash
python -m video_harness plan-video runs/<run>
```

이 명령은 세 실행 계획과 변형 계획을 검증하고 `video-plan.md`를 다시 만든다.
실제 프롬프트·참조·비디오 산출물의 materialization은 아래 `produce`가
`pipeline.output_mode`에 따라 결정한다. output mode가 달라도 세 계획의
커버리지, 스토리 사실, 과학 관계 owner는 바꾸지 않는다.

`video-plan.md`는 씬별 영상대본과 기술 부록을 남긴다. 별도의 사람 영상대본 승인은 받지 않는다. 최초 영상 아이디어와 승인된 대본을 바탕으로 계획을 완성하면 바로 `preview`를 실행한다. 계획·과학·글자 검증은 유지하며 실패하면 고친 뒤 재시도한다. `video-plan-approval.json`의 `source: automatic_validation`은 계획 해시를 묶는 자동 검증 기록이며 사람 승인으로 보고하지 않는다.

## 8. settings-aware 제작과 QA

새 화면 배치는 전체 렌더 전에 대표 장면과 변화 전·중·후 프레임으로 확인한다.
`video_harness/agent/templates/visual-review.md`를 실행 폴더의
`visual-review.md`로 복사해 `DIRECTION.md`의 시각 검토를 기록한다. 큰 글자와
이미지, 겹침·잘림, 불필요한 하단 문구, 모든 장면의 움직임, 전환의 연속성을
실제 프레임과 연결한다. 시각 수정에서는 기존 음성 재사용 여부도 확인한다.
이 기록은 에이전트의 시각·내용 검토이며 아래 CLI 검사와 함께 수행한다.

계획을 작성하면 별도의 영상대본 승인 없이 대표 프레임을 렌더하고 검토 웹을 자동으로 연다.

```bash
python -m video_harness preview runs/<run>
```

`preview`는 비트 중앙과 전환 전·중·후 프레임을 초본 해상도로 렌더해
`previews/preview/contact-sheet.png`, `preview-report.json`, `text-preview-gate.json`
을 만든다. 고정 양식의 웹에서 대본·영상대본·이미지를 함께 제시하고 장면별 수정 의견 또는 프리뷰 승인을 받는다. `preview-feedback.json`의 의견을 반영하고 다시 `preview`를 실행한다. 화면만 다시 열 때는 `preview-ui`를 쓴다.
웹의 프리뷰 승인 버튼 또는 대화 승인 뒤 `approve-preview`가 계획 검증·프리뷰 보고서·렌더러 소스 해시를
`preview-approval.json`에 묶는다. `keywords` 실행의 `produce --quality draft`는 이
승인이 현재 상태일 때만 시작한다.

```bash
python -m video_harness approve-preview runs/<run>
python -m video_harness produce runs/<run> --quality draft
```

`produce`와 `produce-local`의 기본 품질은 `draft`다. 저해상도 초본 QA가
통과하면 `final-draft.mp4`의 재생 링크를 대화에 먼저 제공한다. 장면별 초본은
`videoFiles/draft/`에 있다. schema-v6는 `runtime_defaults.py`의 긴 변 384px·9fps를
사용하며 화면 비율을 따른다. 이전 schema는 `run-settings.json`의 `render.draft_*`를
유지한다. 초본용으로 설정 스냅샷을 다시 쓰지 않는다. 사용자가 초본을 요청한
경우 초본을 전달하고 피드백을 받는다. 고해상도 제작 요청이 있으면 다음을
실행한다. 최종본까지 이미 허가받았다면 초본 링크를 먼저 제공하고 이어가며
같은 허가를 다시 요청하지 않는다.

초본을 제시하고 사람이 정확히 `초본승인`이라고 답하면 `approve-draft`가
`final-draft.mp4`·초본 QA·프리뷰 승인 해시를 `draft-approval.json`에 묶는다.
`keywords` 실행의 최종 제작은 이 승인이 현재 상태일 때만 시작한다.

```bash
python -m video_harness approve-draft runs/<run>
python -m video_harness produce runs/<run> --quality final
```

`produce`는 effective settings를 resolve하고 새 실행에는 `run-settings.json`을
원자적으로 남긴다. 모든 output mode에서 유효한 측정 TTS와 현재
`video-plan-approval.json`을 요구한다. 승인 파일이 없거나 계획 해시가 바뀌면
프롬프트 생성과 렌더를 시작하기 전에 실패한다. `all`은
선택한 품질의 로컬 비디오와 QA 및 프롬프트를 만들고, `final`에서는 온라인
참조와 최종 산출물까지 만들며,
`video_only`는 프롬프트·참조를 생략해 로컬 비디오와 QA만 만들며,
`prompts_only`는 프롬프트와 메타데이터만 만든다. `prompts_only`는 렌더, QA
프레임 추출, 참조 비디오, 변형 합본을 시작하지 않는다.
`video_only`도 승인된 `video-plan.md`와 `video-plan-approval.json`을 삭제하거나
바꾸지 않는다.

비디오를 만드는 mode에서는 `produce`가 초안 렌더와 QA를 먼저 거친다.
`draft` 실행은 이 단계에서 종료하고 초본 경로를 출력한다. QA는
schema-v6의 고정 0.5초 간격·8열(이전 schema는 effective settings의
`render.preview_interval_seconds`·contact-sheet 열 수)과 QA 허용 오차로 프레임 수, 오디오 끝 무음, 상태 지문,
레이어 연속성, 시뮬레이션 시간과 선언되지 않은 정지를 검사한다. 초안 QA가
통과하지 않으면 최종 렌더를 시작하지 않는다. 캐시를 무시하려면 `--force`를
쓴다.

최종 단계는 격리된 스테이징 폴더에서 시퀀스, 필요 시 V2V 참조, 최종 QA와
effective `pipeline.variant_mode`가 선택한 변형을 만든다. 모든 게이트가
통과한 뒤에만 기존 공개 파일을 교체하며, 실패하면 이전 최종본·변형·보고서를
복원한다. `pipeline-report.json`은 mode, variant mode, settings hash와
generated/reused/planned/skipped 산출물을 기록한다.

## 9. mode별 공개 산출물

출력은 다음과 같다.

- `videoFiles/sequences/final/<시퀀스>.mp4`: 음성이 없는 연속 시퀀스 마스터
- `videoFiles/sequences/final/<시퀀스>-narrated.mp4`: 음성이 있는 시퀀스 마스터
- `videoFiles/original/`: 음성이 없는 나레이션 씬별 원본
- `videoFiles/`: 음성을 합친 나레이션 씬별 영상
- `videoFiles/onlineReferences/`: `all` mode의 온라인 V2V용 최종 반열림 프레임 참조
- `videoFiles/previews/half-second/`: 비디오 mode의 configured interval PNG와 접촉 시트
- `video-only.mp4`: 음성이 없는 최종 합본
- `final.mp4`: 음성이 포함된 최종 합본
- `videoFiles/variants/02_explain.mp4`: `four` mode의 설명 중심 최종본
- `videoFiles/variants/03_dynamic.mp4`: `four` mode의 동적 최종본
- `videoFiles/variants/04_cinematic.mp4`: `four` mode의 시네마틱 최종본
- `videoFiles/variants/video-only/`: 위 세 편의 무음 원본
- `videoFiles/variants/variants.json`: 레시피, 해시, 재사용 수와 검증 결과
- `qa-report.json`: 공개된 최종 QA
- `local-production-report.json`: 비디오 mode의 입력 해시와 공개 산출물 생명주기 보고서
- `pipeline-report.json`: 모든 `produce` 실행의 mode-aware 산출물 보고서
- `shorts/shorts-<lang>.mp4`: 최종 제작 직후 만드는 언어별 세로 쇼츠(1080×1920).
  `in_shorts: false` 장면을 잘라 내고 1.15배속으로 줄이며, 3분을 넘으면 만들지 않는다.
- `upload.md`: 언어별 영상·쇼츠 제목과 설명, 3D 모델·배경음악·음성 모델 출처 표기
- draft 실행은 `videoFiles/sequences/draft/`, `video-only-draft.mp4`,
  `final-draft.mp4`를 사용한다.

비디오 mode의 마지막에는 실행 폴더 전체를 검증한다.

```bash
python -m video_harness validate runs/<run>
```

## 10. schema-v1 호환 명령

schema-v1 실행의 루트 `videoPrompt/`, 샷 기반 `render-production`, 기존
`simulation.json` 렌더와 검증은 그대로 유지한다. 새 schema-v2 실행의 기본
경로는 위의 `plan-video`와 `produce`이다.

기존 실행을 새 구조로 변환:

```bash
python -m video_harness migrate-production runs/<run> --schema-version 1
```

기존 시뮬레이션 전용 호환 명령:

```bash
python -m video_harness render runs/<run> --quality draft
```

현재 화성 역행 템플릿은 원형 궤도 교육 모델을 사용한다. 실제 천문력 재현이 아니라 `지구와 화성은 같은 방향으로 공전하지만 지구의 각속도가 더 빠르고, 충 부근에서 별 배경상의 시선 방향이 잠시 반전된다`는 원리를 정확히 보여주는 용도다.

schema-v1 샷 기반 실행은 기존 `render-production`과 `review-shot` 명령을
사용한다. 이 호환 명령들은 마이그레이션 전 재현성과 긴급 호환을 위한 것이며
새 제작 계획의 기본 명령이 아니다.

호환 렌더는 Three.js를 호출하는 경로이며 Python 3D 렌더러가 아니다.
최종본의 직접 공개는 차단된다. 새 구조로 이전하려면 위 명령의
`--schema-version 1` 대신 `--schema-version 2`를 사용하고, 질문 사슬·연속성
검토와 영상 생성대본 승인을 거쳐 `produce`로 제작한다.

3D 구현은 Blender MCP/네이티브 Blender를 우선하고 Three.js도 허용한다.
독립적인 Python 3D 렌더 경로는 추가하지 않는다.
[하네스 구조](../docs/architecture.md)의 역할 구분을 따른다.

## 필수 질문 사슬·렌더 연속성 경계

[필수 검사 절차](../docs/creative-gates.md)를 제작 흐름에 적용한다.
대본 확정 전에 `story-chain.json`을 작성하고 `check-creative story`를 통과한다.
영상 계획에는 모든 인접 beat의 `continuity-plan.json`을 포함하고
`check-creative plan`을 통과한 뒤 검토본을 생성한다.
초안과 최종 QA는 실제 렌더 변환을 검사하며, 최종 공개 직전 다시 검사한다.
누락·실패·오래된 검토는 중단 조건이다. 원인을 수정하고 같은 검사를 반복한다.

### 업로드 설명의 홍보 링크

새 실행의 `promotion.base_url`과 `promotion.locale_mode`는 설정 창에서 정하고
`run-settings.json`에 고정한다. 기본 주소가 비어 있으면 홍보를 넣지 않는다.
`shared`는 모든 언어에 같은 주소, `language_path`는 한국어에 기본 주소와
나머지 언어에 `/en`, `/ja`, `/zh`, `/es` 경로를 사용한다. `upload-text`가
본편·쇼츠 설명에 해당 주소를 넣고 모델·음악 출처는 마지막에 유지한다.
대본·번역·음성을 홍보 링크 때문에 고치지 않는다. 공용 설정의 기본 주소는
빈칸이며 개인 홍보 값은 Git 제외 파일 `settings.local.json`에 저장한다.

### 최종 제작 뒤 로컬 전달

`produce --quality final`은 최종 검사·쇼츠·업로드 문구 생성이 모두 성공하면
선택적 로컬 전달 모듈을 자동 호출한다. `.local-integrations/`의 구현·인증·설정·
토큰은 Git 제외 대상이며 공개 하네스에는 호출 연결부만 둔다. 모듈이 없으면
영상 제작은 그대로 완료한다. 전달 실패 시 영상을 다시 렌더하지 않고
`delivery-report.json`을 확인한 뒤 `python -m video_harness deliver runs/<run>`으로
재시도한다. 외부 게시 완료는 별도 보고서의 성공 상태와 실제 URL을 확인해 알린다.
사용자가 승인한 로컬 업로더 설정에 따라 동작하며 초본은 업로드하지 않는다.
