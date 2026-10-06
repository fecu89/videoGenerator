# 영상 계획 진입점

기본 정책 `text_policy: subtitles`에서는 **화면 글자 없음**이다. 제목·라벨·지시선·
수식·단위를 장면 객체로 넣지 않고 설명은 나레이션과 언어별 자막이 맡는다.
`labels`는 `keywords` 정책을 명시한 실행에서만 쓴다.

먼저 `video_harness/agent/DIRECTION.md`의 기본 연출 기준을 읽는다. 객체가
주인공이며 글자는 비트당 핵심 단어 2개를 `labels`로 선언해 지시선으로 잇는다.
글자 배경판·부제목·하단 보조 문구는 없다. 모든 장면의 의미 있는 움직임과 전환을
계획하며, 프리뷰·초본 검토는 해당 문서의 시각 검토 양식을 사용한다.

주요 객체는 `DIRECTION.md`의 **기본 화면 크기**를 기본값으로 적용한다. 이 기준을
공통 라우팅, 로컬 구도, 온라인 대안과 시각 검토까지 전달한다.

[연속 전환 규칙](../../docs/continuous-transitions.md)을 함께 적용한다. 앞 장면의
대상을 확대·분리·집결하거나 퇴장·진입시켜 다음 설명으로 이어간다. 추적할
객체와 공통 시간을 계획에 남기고, 나레이션 경계마다 화면을 교체하지 않는다.

확정되고 검증된 `script.json`, 실제 음성 길이, 그리고 effective settings를
기준으로 schema version 2 영상 계획을 작성한다. 먼저
`python -m video_harness settings [run]`으로 비밀값 없는 현재 설정을 읽는다.
새 실행에 스냅샷이 없으면 `[run]` 없이 읽는다. 새 계획의 기본 렌더 값은
`render.final_width`, `render.final_height`, `render.final_fps`를 사용한다
(내장 예시: 1920×1080, 30fps). 기존 계획이 소유한 크기와 canonical FPS는
언제나 그 계획을 따른다.

schema-v6 프리뷰는 긴 변 384px·9fps, QA 추출 0.5초·접촉 시트 8열로 고정한다.
이전 schema는 `render.preview_interval_seconds`와 `render.contact_sheet_columns`를
포함한 당시 렌더/QA 출력 계약을 유지한다. `pipeline.variant_mode`
는 최종본 materialization만 바꾼다. `four`의 내장 예시는 balanced와 세 대안을
만들고, `balanced_only`는 balanced만 만든다. 둘 중 어느 경우에도 네 레시피를
포함한 `variant-plan.json`, 스토리 사실, 공통 visual_beat의 계획 커버리지는
바꾸지 않는다. `pipeline.output_mode`는 `produce`가 프롬프트, 비디오 또는 둘
다음을 materialize할지 결정할 뿐, 아래 세 계획의 과학적 라우팅과 커버리지는
바꾸지 않는다.

세부 규칙을 이 파일에서 추측하거나 중복하지 않는다. 다음 문서를 반드시 아래 순서로 사용한다.

1. `video_harness/agent/prompts/video-router.md`를 처음부터 끝까지 읽고 `production-plan.json`을 작성한다.
2. `video_harness/agent/prompts/video-local.md`를 처음부터 끝까지 읽고 `local-sequence-plan.json`을 작성한다.
3. `video_harness/agent/prompts/video-generated.md`를 처음부터 끝까지 읽고 `online-plan.json`을 작성한다.

세 계획의 `script_sha256`와 `production_plan_sha256`를 현재 파일에 결합한 뒤 다음 명령으로 검증하고 모든 검토 문서와 온라인 프롬프트를 컴파일한다.

```bash
python -m video_harness plan-video runs/<run>
```

`production-plan.json`은 공통 시각 사건과 라우팅의 기준이고, 로컬과 온라인 계획은 그 기준을 실행 가능한 두 제작 계약으로 구체화한다. schema version 2에서는 루트 `videoPrompt/`를 만들지 않는다. schema version 1 실행은 기존 샷 계획과 루트 프롬프트 호환 경로를 그대로 사용한다.

스토리 검토 때 받은 영상 아이디어(`story-feedback.json`의 `visual_brief` 및 최초 대화 지시)를 반영한다. 아이디어가 없으면 대본에 맞게 연출을 정하며 추가 입력을 요구하지 않는다.

별도 `영상대본승인`을 요청하지 않는다. 계획 작성 뒤 바로 다음 명령으로 계획 검증 → 대표 프레임 렌더 → 검토 웹 열기까지 진행한다.

```bash
python -m video_harness preview runs/<run>
```

웹에서 현재 대본·영상대본·프리뷰를 같이 보여주고 수정 의견을 받는다. `preview-feedback.json`을 읽고 장면별 수정 의견을 반영한 뒤 프리뷰를 갱신한다. 프리뷰 승인을 받기 전에는 전체 `produce`를 실행하지 않는다. 화면만 열 때는 `preview-ui runs/<run>`을 사용한다.

## 필수 3D 전환 검토 산출물

계획 컴파일 전에 `continuity-plan.json`을 작성한다. 모든 인접 beat에
`continuous_3d`, `match_cut`, `cut` 중 하나와 구체적 이유를 기록한다.
연속 장면에는 같은 대상의 앞뒤 오브젝트 이름을 연결한다. 관측 기준에 따른
회전·가림·굴절 방향은 `direction_checks`로 명시한다. 이어질 수 없는 장면은
이유 있는 컷으로 처리한다. [필수 게이트 명세](../../docs/creative-gates.md)를
따라 계획 및 실제 렌더가 실패하면 수정·재검사를 반복하고 최종 저장을 막는다.
