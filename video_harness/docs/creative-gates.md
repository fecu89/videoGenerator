# 질문 사슬과 3D 연속성 필수 검사

이 검사는 권고가 아니라 제작 경계다. 검토가 없거나 `pending`·`failed`이거나
현재 입력과 맞지 않으면 다음 단계로 넘어가지 않는다. `--force`는 캐시 재생성
옵션이며 이 검사를 우회하지 않는다. 실패한 항목을 수정하고 같은 검사를 다시
통과할 때까지 음성 생성·영상 승인·최종본 저장을 완료로 보고하지 않는다.

## 1. 대본의 질문 → 답 → 다음 질문

`story-chain.json`을 [스키마](../schemas/story-chain.schema.json)에 맞게 작성한다.

- `script_sha256`: `creative_gates.story_digest(script)`로 계산한다. 음성 파일 경로와
  측정 길이처럼 내용과 무관한 메타데이터는 제외한다.
- `scene_coverage`: 모든 씬을 순서대로 검토한다. 도입은 첫 씬, 마무리는 마지막
  씬에만 허용한다. 중간 원리 설명은 질문과 그 답 사이에 연결한다.
- `pairs`: 최소 두 질문·답 쌍. 각 질문과 답의 실제 나레이션 인용, 씬 번호,
  답이 질문을 해결하는 이유를 기록한다. 마지막 답을 제외하고 **그 답 때문에
  다음 질문이 생기는 이유**도 구체적으로 적는다. 단순히 주제가 비슷하거나
  “그런데”가 있다는 이유로 통과시키지 않는다.
- 암묵적 질문도 실제 문장을 인용하고 그 의문을 검토 이유에 명시한다.
  명시적인 물음표 문장은 검토에서 누락할 수 없다.
- 마지막 답은 사슬을 닫는다. `causes_next_question`과 `next_question_reason`은
  마지막 쌍에서 `null`이다.

인과관계의 의미 판단은 Codex 또는 사람이 실제 대본을 읽고 수행한다. Python은
그 판단의 인용 근거·순서·전체 커버리지·판정·현재 파일과의 일치를 검사한다.
문자열 검사만으로 인과관계를 이해하거나 자동 보증한다고 주장하지 않는다.
불합격을 통과로 바꾸기 위해 이유를 지어내지 않는다. 대본이 문제라면 대본을
고친 뒤 변경된 나레이션에 필요한 사용자 승인을 받는다.

```bash
python -m video_harness check-creative story runs/<run>
```

`voice`는 이 검사를 통과하기 전에 모델을 로드하거나 음성을 만들지 않는다.

## 2. 모든 장면 경계의 전환 계획

`continuity-plan.json`을 [스키마](../schemas/continuity-plan.schema.json)에 맞게
작성한다. `local_sequence_plan_sha256`은 로컬 계획 파일의 SHA-256이다.
모든 인접 beat 경계를 순서대로 한 번씩 기록한다.

[연속 전환 규칙](continuous-transitions.md)에 따라 앞 대상에서 다음 설명으로
이어지는 확대·분리·집결·퇴장과 진입을 먼저 계획한다. 대상이나 규모의 변경만으로
컷을 선택하지 않는다. 아래 모드의 적절성과 설명 관계는 실제 콘티를 읽고 판단한다.

| 모드 | 적용 기준 | 실제 렌더 검사 |
|---|---|---|
| `continuous_3d` | 같은 공간·시간에서 추적 대상을 유지하며 확대·분리·집결 또는 퇴장·진입 | 선언된 객체·카메라 위치, 회전, 배율, 투영과 시간의 경계 불연속 |
| `match_cut` | 관측 화면의 대상 위치와 크기를 맞추어 전환 | 카메라 투영 후 위치·크기 |
| `cut` | 서로 다른 관측 장소·시간 등 연속 연결이 설명을 흐리는 경우 | 연속 이동 검사는 생략하되 컷의 구체적 이유와 검토 판정 필수 |

연속 전환에는 앞뒤 오브젝트 이름을 `actors`의 `from`/`to`에 연결한다.
실제로 이어서 추적할 객체를 등록하며 장면과 무관한 정지 객체로 대신하지 않는다.
이어질 수 없는 장면을 억지로 연결하지 않는다. 컷을 연속성 실패를 숨기는
수단으로 바꾸지 말고, 편집상 이유를 실제 콘티와 함께 검토한다.

`direction_checks`에는 관측 기준에 따른 중요한 방향을 명시한다.
`screen_direction`은 세계 좌표 또는 지정한 객체의 로컬 벡터를 카메라 화면에
투영한다. `screen_rotation`은 지정 구간에서 60도 이상 일관된 시계/반시계
회전을 검사한다. `path_direction`은 렌더 메시에서 캡처한 경로의 세계 좌표
방향과 단조 진행을 검사한다. 예: 월식 화면의 반시계 회전, 달 왼쪽의 그림자
진입 경계, 지구 위 대기를 통과한 단일 투과광이 지구 쪽으로 휘는 경로.
방향이 중요한 제작에서는 이 목록을 비우지 않는다.

```bash
python -m video_harness check-creative plan runs/<run>
python -m video_harness plan-video runs/<run>
```

전환 검토표는 `video-plan.md`에도 포함된다. 영상 승인은 대본·네 계획·영상
검토본뿐 아니라 두 검토 JSON의 해시에도 결합된다. 수정되면 다시 검토한다.
기존에 사용자가 명시적으로 승인한 시각 수정 범위 안의 구현은 그 지시를 따른다.

## 3. 실제 렌더와 최종 저장

Blender는 평가된 `matrix_world`, Three.js는 갱신된 `matrixWorld`를 캡처한다.
선언된 연속 경계에서 캡처 누락·잘못된 수치·천체 순간 이동·카메라 회전 점프는
실패다. 이전 세 표본의 위치로 다음 위치를 예측하므로 매끄러운 가감속은 허용한다.
검사는 경계 주변 표본과 명시한 방향 구간을 다룬다. 화면 글자는 별도의 `text`
게이트가 검사한다. `text-plan-gate.json`(승인 시: 라벨 계약, 산문 속 문구,
`subtitles` 제외), `text-preview-gate.json`·`text-draft-gate.json`·
`text-final-gate.json`(렌더 시: `label_clipped`, `label_overlap`,
`label_covers_object`, `leader_detached`, `label_not_rendered`,
`label_anchor_behind_camera`). `text_policy: subtitles` 실행에서는 `kind: formula`가 아닌 라벨 선언이
`labels_forbidden`, 선언하지 않은 콜아웃·글자 객체가 `callouts_forbidden`·
`on_screen_text_found`로 실패한다. 선언한 수식 콜아웃은 위 렌더 검사를 받되, 설명하는 도형(막대 등)에 붙여 두므로 `label_covers_object`는 제외하고 실제 프레임으로 가림을 검토한다. Three.js 시퀀스는 상태 샘플에
`canvas_text_calls: 0`을 기록해야 하며, 없으면 `on_screen_text_unverifiable`로
닫힌다(기존 Three.js 시퀀스는 캔버스 글자를 그리므로 `subtitles` 실행에 쓸 수
없다). `text_policy: legacy` 실행은 `skipped`로 통과한다.

다국어 자막 제작은 네 게이트를 더 거친다. `translation-gate.json`(번역 누락·
해시·길이 예산·문장 종결), `translation-fit-gate-<lang>.json`(장면 배율 ≤1.25,
`scene_too_long`, 무음·클리핑), `subtitle-gate-<lang>.json`(`cue_outside_window`,
`cue_overlap`, `cue_too_many_lines`, `cue_line_too_long`, `cue_too_short`),
`localization-draft-gate.json`·`localization-final-gate.json`(`localized_missing`,
`localized_length_mismatch`, `localized_no_audio`, `subtitle_gate_failed`).
영상 전체의 물리적 정확성과 미학은 여전히 직접 검토하며, 대표 프레임과 전환
전·중·후의 시각 검토도 기록한다.

확대 중 내부 구조의 가림, 분리 중 남은 긴 결합선, 집결 중 겹침과 화면 잘림,
글자 크기와 배치는 실제 MP4의 전환 프레임 및 움직임으로 확인한다. 먼저
`check-creative render runs/<run> --quality draft`와 초본 QA를 통과한 저해상도
초본을 전달한다. 아래 최종 품질 검사는 고해상도 제작 단계에서 실행한다.

```bash
python -m video_harness check-creative render runs/<run> --quality final
python -m video_harness validate runs/<run>
```

초안 QA 실패는 최종 렌더를 막는다. 최종 QA 실패는 공개 파일 복사를 막는다.
최종 파일을 저장하기 직전에도 현재 승인과 실제 렌더 보고서를 다시 검사한다.
실패 보고서는 `story-gate.json`, `continuity-plan-gate.json`,
`continuity-final-gate.json` 및 QA 보고서에 남는다. 기존 완성본은 보존한다.

이전 `render` / `render-production` 경로로 최종본을 직접 저장하는 방식은
금지한다. 기존 실행은 시퀀스 계획과 두 검토를 갖춘 `produce` 경로로 옮긴다.
검토 없는 예전 실행의 `validate`도 통과하지 않는다.

## 실패 시 반복 절차

1. 실패 보고서의 항목과 실제 대본·프레임을 확인한다.
2. 원인이 대본, 콘티, 렌더러, 누락된 캡처 중 어디인지 구분해 수정한다.
3. 변경된 입력의 검토와 필요한 승인을 갱신한다.
4. 실패했던 검사와 영향을 받는 렌더·QA를 다시 실행한다.
5. 모두 통과한 경우에만 완성본을 저장하고 작업 완료를 보고한다.
