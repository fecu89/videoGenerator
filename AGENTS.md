# Video Generator Agent Bootstrap

이 프로젝트에서 새 영상 제작을 시작할 때는 다음 순서를 지킨다.

1. `settings.md`를 처음부터 끝까지 읽는다.
2. `python -m video_harness settings-ui`를 실행하고 명령을 열린 상태로 둔다.
   브라우저가 열리면 **영상 템포·목소리·배경음악·출력**을 정한다.
   목소리 일관성이 중요하면 같은 화자와 톤 프리셋을 유지한다.
   사용자가 설정을 고르고 **저장 후 닫기**를 누를 때까지 기다린다.
3. 서버가 종료되면 `python -m video_harness settings`로 새 실행에 적용할
   `settings.json` 값을 확인한다.
4. `video_harness/agent/WORKFLOW.md`를 처음부터 끝까지 읽고 조사와 전체 대본
   초안까지만 작성한다.
5. `story-ui runs/<run>`으로 현재 전체 대본을 웹에 제시하고 영상 아이디어(선택)와 수정 의견을 함께 받는다. 수정 요청을 반영할 때마다 웹을 새로 제시한다.
6. 사람이 현재 대본을 명시적으로 승인하기 전에는 다음 명령이나 TTS·영상
   계획·렌더링에 해당하는 다른 작업을 실행하지 않는다.

```bash
python -m video_harness voice runs/<run>/script.json
python -m video_harness translate-scaffold runs/<run>
python -m video_harness voice runs/<run>/script.json --target-language all
python -m video_harness plan-video runs/<run>
python -m video_harness produce runs/<run>
```

한국어 음성이 확정되면 `translate-scaffold`가 장면별 말하기 예산이 든
`translations.json` 틀을 만든다. 에이전트가 `text`에 영어·일본어·중국어·
스페인어 번역을 채운 뒤 `voice --target-language all`로 언어별 음성을
합성한다. 엔진·모델·화자는 `language-voices.json`이 정하고, 각 장면은 한국어
장면 길이에 맞춰 속도 보정(`voice.max_tempo_factor` 상한)되며 넘치면 그 장면 번역을 줄인다.
번역과 다른 언어 음성에는 사용자 승인·청취 검토가 없고 게이트만 통과하면 된다.
완성 단계의 다국어 산출물은 설정 `local_video.localized_delivery`로 정한다.
`burned_videos`(기본)는 `final.mp4`(한국어, 자막 없음)와 함께 언어별로 자막을
번인한 `final-ko.mp4`, `final-en.mp4`, `final-ja.mp4`, `final-zh.mp4`,
`final-es.mp4`를 같은 길이로 만든다. `audio_tracks`는 자막 없는 `final.mp4`
하나에 영상과 길이가 같은 언어별 오디오 트랙 `final-<lang>.m4a`를 낸다. 두 경우
모두 `subtitles/<lang>.srt|.ass`를 함께 만들고 배경음악·더킹은 동일하게 적용한다.
사용자는 실행을 시작할 때 설정 화면에서 이 값을 고른다.

설정 승인, 과거의 일반적인 “진행해”, 침묵은 대본 승인이 아니다. 승인 뒤에
대본을 다시 고쳤다면 새 버전도 사람에게 다시 보여주고 승인받는다.

7. 대본은 `story-review.md`와 `script.json`으로 저장한 뒤 `python -m video_harness story-ui runs/<run>`으로 웹을 연다. 장면별 대본·수정 의견과 **영상 아이디어(선택)**를 함께 받는다. 사용자가 이미 대화에서 준 영상 아이디어도 보존한다. 아이디어가 없으면 다시 묻거나 기다리지 않고 대본에 맞게 연출을 정한다.
   `story-feedback.json`을 확인해 수정 사항을 반영하고 웹을 다시 제시한다. 웹의 **대본 승인**(현재 script 해시와 결합한 `story-approval.json`) 또는 대화의 명시적 대본 승인을 받은 뒤에 음성을 만든다. 웹의 저장 버튼만 누른 것은 승인이 아니다.
8. 승인된 대본과 검증된 음성, 최초 영상 아이디어를 바탕으로 네 영상 계획과 연출을 작성한다. 별도의 `영상대본승인`을 요청하지 않는다. 다음 명령은 계획 컴파일·과학/글자 게이트 검증 → 대표 프레임 렌더 → **검토 웹 자동 열기**까지 이어진다.

```bash
python -m video_harness preview runs/<run>
```

   검토 웹의 고정 양식은 `video_harness/review_web/`에 둔다. 새 영상마다 HTML을 만들지 않고 실행 폴더의 대본·영상대본·프리뷰 이미지를 파라미터로 채운다. 프리뷰를 다시 렌더하지 않고 화면만 열 때는 `python -m video_harness preview-ui runs/<run>`을 쓴다. `--no-ui`는 자동 검사 전용이다.
   `video-plan-approval.json`은 호환 파일명으로 유지하되 `source: automatic_validation`이면 사람의 승인이 아닌 계획 검증 기록이다. 에이전트는 프리뷰의 시각 검사와 게이트를 확인한다.
   수정 의견이 있으면 프리뷰 승인을 막는다. 웹의 **수정 반영 후 프리뷰 다시 만들기** 버튼은 의견과 `preview-regeneration-request.json`을 함께 저장한다. 서버는 요청을 자동으로 LLM에 전달하지 않으므로 에이전트가 현재 검토 세션에서 이 파일과 서버 출력의 입력 이벤트를 확인한다. `status: queued` 요청을 받으면 `feedback`의 수정 사항을 반영하고 `preview-ui.update_regeneration(run, 'applying', '수정 의견을 반영하고 있습니다.')`로 상태를 표시한다. 대본을 바꾸는 요청은 대본 승인 절차를 따르며, 화면 수정은 중간 승인 없이 반영하고 `preview --no-ui`를 실행한다. 이 명령이 렌더 중·완료·실패 상태를 기록하고 열린 웹은 새 프리뷰 보기 버튼을 표시한다. 수정 없이 같은 프리뷰를 다시 렌더해 반영했다고 처리하지 않는다.
   웹의 장면별/전체 수정 의견은 `preview-feedback.json`에 저장된다. 사용자가 저장하면 에이전트가 이를 읽어 계획·연출을 수정하고 프리뷰를 다시 만든다. 저장된 의견은 자동 코드 수정 명령이 아니며 에이전트가 내용을 해석해 반영한다. 승인 전에는 `produce`를 실행하지 않는다.
9. 웹에서 **프리뷰 승인** 버튼을 누르거나 대화에서 `프리뷰승인`이라고 답하면 초본을 만든다. 웹 승인은 이미 `preview-approval.json`을 기록하므로 CLI 승인을 중복 실행하지 않는다.

```bash
# 대화에서 승인했을 때만:
python -m video_harness approve-preview runs/<run>
python -m video_harness produce runs/<run> --quality draft
```

   초본 QA가 통과하면 음성이 포함된 `final-draft.mp4`와 QA 결과를 즉시 제시하고 `초본승인`을 기다린다. 그 뒤에만 다음을 실행한다.

```bash
python -m video_harness approve-draft runs/<run>
python -m video_harness produce runs/<run> --quality final
```

대본·계획·렌더러·프리뷰가 바뀌면 이전 프리뷰 승인을 재사용하지 않는다. 계획 수정은 중간 승인 없이 검증·프리뷰·웹 재검토로 이어간다. 대본 자체가 바뀌면 대본 웹에서 새 승인을 받는다. 기존 `text_policy: legacy` 실행의 제작 호환 경로는 유지한다.

긴 렌더는 에이전트가 반복해서 로그를 조회하며 기다리지 않는다. 제작 프로세스를
유지한 채 아래 고정 로딩창을 열고 사용자에게 주소를 전달한다. 브라우저가 진행률을
자동 갱신하고, 프로세스 종료와 이번 실행의 QA 통과·산출물 게시를 확인하면 영상을
표시한다. `PID`는 `produce` 부모 프로세스, `STAGING`은 해당 실행의 `.local-*`
폴더, `TOTAL`은 해당 품질의 전체 시퀀스 프레임 수다. 렌더가 실행 중일 때 연결한다.

```bash
python -m video_harness progress-ui runs/<run> --pid PID --staging STAGING --total-frames TOTAL --quality final
```

로딩창과 제작 프로세스를 실행 상태로 두고 대화는 마무리한다. 완료 전에는 완성으로
보고하지 않으며, 오류 확인이나 사용자 요청이 있을 때만 다시 개입한다.

테스트, 문서 편집, 읽기 전용 점검에는 설정 화면을 열지 않는다. 기존 실행은 `run-settings.json`을 계속 사용하며 사용자가 명시적으로 요청하지 않는 한 `--refresh-settings`를 실행하지 않는다. 설정을 바꾸기 위해 구현 상수를 직접 수정하지 않는다.

## 공통 연출 기준

글자와 주요 객체의 기본 크기는 **2026-09-22 와도 영상에서 확대한 현재 크기**로
고정한다. 이전 기본 구도보다 1.5배 커진 상태가 새 기본값이며, 새 작업이나 수정
때마다 다시 1.5배를 곱하지 않는다. 새 계획·렌더러·온라인 대안 모두
[기본 화면 크기](video_harness/agent/DIRECTION.md#기본-화면-크기)를 적용하고,
짧은 문구(예: `관람차 객실`)는 줄바꿈하지 않고 한 줄에 두며, 넘칠 때만 그
문구를 한 줄에 맞게 줄인다. 문장처럼 긴 설명은 단계 분리·재배치로 해결한다.
전체 글자나 대상을 작게 줄여 빈 화면으로 돌아가지 않는다.

대본의 [문장별 연기](video_harness/docs/voice-acting.md)는 현재 실행의 실제
음성 설정에 맞춘다. `voice.emotion_mode=off`이면 `sentence_delivery`를 생략하거나
빈 배열로 두고, 대화의 대본·`story-review.md`에도 감정·강도 표기를 붙이지 않는다.
`script_only`일 때만 모든 문장의 감정·강도를 작성하고 검토본에 표시한다.
선택된 전체 말투는 유지하며, 문장별 연기를 켜거나 기본 말투를 임의로 바꾸지 않는다.
연기 모드에서 누락된 문장은 생성 전에 차단한다.

3D 장면은 Blender MCP와 Blender 네이티브 렌더를 우선 사용하며 Three.js도
허용한다. 독립적인 Python 3D 렌더러를 추가하거나 실패 시 대체 경로로 쓰지
않는다. Blender 내부 `bpy` 장면 코드와 Python의 계획·물리 계산·Qwen3-TTS·Kokoro·QA·
FFmpeg 호출은 필요한 하네스 코드다. 렌더러 선택은 계획에 명시하며 기존
실행의 선택을 임의로 바꾸지 않는다. 구조와 의존성은
[하네스 구조](video_harness/docs/architecture.md)를 따른다.

대본·화면·영상의 제작 또는 수정을 시작할 때
`video_harness/agent/DIRECTION.md`를 읽고 적용한다. 사용자가 확정한 질문 사슬,
밝은 도입, 큰 이미지·글자, 대상과 글자의 영역 분리, 배경판·하단 보조 문구
제거, 의미 있는 3D 움직임과 전환 원칙을 모은 기준이다. 현재 사용자의
명시적인 지시가 기본 연출 기준보다 우선한다.

전체 렌더 전에 대표 프레임을 검토하고, 완성본에서는 이 문서가 가리키는
시각 검토 양식과 기존 미디어 검사를 함께 사용한다.

영상 전환은 [대상을 이어가는 전환](video_harness/docs/continuous-transitions.md)을
기본으로 설계한다. 전체에서 내부로 확대하거나, 한 단위에서 물러나 집결을
보여주거나, 구성 요소 하나를 다음 구조까지 유지한다. 같은 객체와 시간축을
이어가며 나레이션 씬 경계마다 화면을 교체하지 않는다. 확대·대상 변경만으로
컷을 선택하지 말고 연결 가능한 관계를 먼저 확인한다. 전환의 전·중·후 프레임과
기존 continuity 게이트를 모두 검토한 저해상도 초본을 먼저 전달한다.

## 필수 제작 검사

모델은 [메모리 수명 규칙](video_harness/docs/architecture.md#모델별-메모리-수명)에
따라 관리한다. 여러 호출에 재사용한 모델은 작업 종료·실패 시 반드시 닫고,
음성 모델을 해제한 뒤 음성 인식 등 다음 모델을 시작한다.

[질문 사슬·3D 연속성 게이트](video_harness/docs/creative-gates.md)를 따른다.
`story-chain.json`과 `continuity-plan.json`의 현재 검토가 없거나 실패하면
다음 제작 단계로 나가지 않는다. 실패 항목을 고치고 재검사할 때까지 반복한다.
`--force`로 우회하거나 실패한 완성본을 전달하지 않는다.
