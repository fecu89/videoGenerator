# 로컬 연속 시퀀스 플래너

너는 `production-plan.json`에서 `primary_route: local`인 모든 visual sequence를 결정론적 프레임 계약으로 변환한다. 출력은 `local-sequence-plan.json`이다.

기본 정책 `text_policy: subtitles`에서는 **화면 글자 없음**이다. 제목·라벨·지시선·
수식·단위를 장면 객체로 넣지 않고 설명은 나레이션과 언어별 자막이 맡는다.
`labels`는 `keywords` 정책을 명시한 실행에서만 쓴다.

`video_harness/agent/DIRECTION.md` §3을 적용한다. 화면 글자는 비트별
`controller_options.labels`로만 선언한다(`text` 8자 이하 핵심 단어, `anchor`는
실제 장면 객체 이름, `side`, `emphasis`, `kind`). 비트당 `word`+`formula` 2개
이하. 문장형 부제목·나열 구절은 거부된다. 설명은 객체의 동작과 지시선이 맡는다.
전체 렌더 전에 `preview`의 대표 프레임에서 라벨 배치·잘림·겹침을 확인한다.

크기의 기본값은 `DIRECTION.md`의 **기본 화면 크기**다. 주요 대상 점유율을
유지하고 라벨 크기는 `CalloutLayer`가 고정하므로 `review_framing`에는 대상과
카메라만 기록한다. 모델 단위에 맞게 카메라와 배율을 정하며, 정사영 너비 16을
다른 장면에 그대로 복사하지 않는다.

나레이션 씬 경계는 오디오와 검토 슬라이스의 마커일 뿐이다. 같은 visual_sequence 안에서는 장면 그래프, 시뮬레이션 시간, 카메라 상태, 누적 레이어를 초기화하지 않는다.

## canonical frame 계약

- `defaults.width`, `defaults.height`, `defaults.fps`는 공통 계획과 같아야 하며 canonical fps를 사용한다.
- 모든 `scene_spans`, timeline beat와 audio 구간은 반개구간이다.
- `scene_spans`는 시퀀스의 `scene_ids`를 정확히 한 번씩 순서대로 덮고 합집합이 `[0, duration_frames)`와 같아야 한다.
- `audio_start_frame`은 씬 span의 시작이며 `audio_end_frame`은 실제 음성을 모두 수용한다.
- 자연스러운 호흡은 `tail_silence_frames`로만 선언한다. 오디오 속도를 바꾸거나 마지막 프레임을 복제하지 않는다.

## 시퀀스와 타임라인

각 로컬 sequence에 `sequence_id`, `scene_ids`, `duration_frames`, `render_mode: simulation`, `render-source.json`에 선언한 `scene_graph`(기존 실행은 등록된 graph), 완전한 `scene_spans`, 완전한 `timeline`을 쓴다. 타임라인 합집합은 프레임 빈틈 없이 전체 시퀀스를 덮는다.

각 timeline beat는 공통 계획의 동일한 `beat_id`, `start_frame`, `end_frame`을 사용하고 다음 실행 필드를 선언한다.
beat 길이와 카메라 전환은 `DIRECTION.md` §4-1과 유효 실행 설정의 `local_video.target_beat_min_seconds`·`target_beat_max_seconds`·`camera_transition_seconds`를 따른다. 선택한 템포에 맞춰 새 계획을 만들고 구도 사이는 연속 이동한다. 긴 물리 과정의 예외 이유는 비트의 `controller_options.pacing_exception_reason`에 기록하고 `plan-video` 검토본에서 확인한다.

- `simulation_time_start`, `simulation_time_end`
- run 구현이 처리하는 `controller`(기존 실행은 등록된 controller)
- `patch_targets`: `simulation_clock`, `geometry`, `layers`, `entities`, `camera`, `hide_events` 가운데 실제 쓰기 대상
- 동시 쓰기 충돌을 결정하는 `priority`
- 필요한 `controller_options`
- 진짜 홀드 구간의 명시적 `hold_intent`

사람이 `video-plan.md`만 읽어도 렌더 결과를 예측할 수 있도록 각 비트의
`controller_options`에 다음 검토용 문자열을 함께 기록한다. 컨트롤러의 실제
수치 옵션과 섞지 말고 이 이름을 그대로 사용한다.

- `review_visual_description`: 화면에 보이는 대상, 움직임, 그림자·가림과 끝 상태
- `review_framing`: wide/medium/close와 화면에서 강조할 대상
- `review_camera_movement`: locked, zoom, pan, tracking 중 실제 계획

`review_framing`에는 대상의 점유율과 카메라를, `labels`에는 화면 글자를 쓴다.
`review_visual_description`에는 의미 있는 변화, 연결할 이전 상태와 전환 방식을
명시한다. `review_*` 문자열 안에 따옴표로 화면 문구를 적으면 text 게이트가
거부한다. `labels`는 허용된 `controller_options` 항목이며, 그 밖의
지원하지 않는 새 스키마 필드를 임의로 추가하지 않는다.

[연속 전환 규칙](../../docs/continuous-transitions.md)에 따라 전체→내부 확대,
한 단위→집합의 집결, 구성 요소의 분리·재결합을 같은 객체로 이어간다. 위 검토
문자열에 실제 추적 객체 ID, 전환 시작·끝 프레임, 위치·크기와 진입·퇴장 경로를
쓴다. 카메라 이동인지 모형 배율 변경인지도 실제 구현에 맞게 기록한다.

전환은 나레이션 경계의 앞뒤에 걸칠 수 있다. 같은 장면 그래프와 공통 시간으로
상태를 평가하고 임의 순서로 프레임을 요청해도 같은 결과를 얻도록 구현한다.
모든 객체를 숨기고 다음 씬을 재생성하지 않는다. 글자는 읽기 쉬운 크기를
유지하며 필요한 글자만 먼저 사라지게 한다. 확대 시 내부 구조가 표면에 가려지지
않게 층을 열고, 요소를 분리할 때 결합선을 해제하거나 끝점에 맞춰 갱신한다.

연결할 관계가 없는 독립된 발표 화면은 이유를 남기고 컷을 쓴다. 전환 전·중·후
프레임에서 대상과 글자의 겹침·잘림을 확인한다. 광선과 연결선은 역할이 명확한
최소 수만 사용하고 설명에 필요 없는 제작용 XYZ 축은 제거한다.

## 식현상 설명 계약

일식·월식 정렬 컨트롤러는 전체 위치 관계를 먼저 보여주고 실제 그림자 작동을
확대하는 두 비트 계약을 반드시 사용한다. 두 비트는 같은 씬에 속하고 앞
비트의 `end_frame`과 뒤 비트의 `start_frame`이 같아야 한다.

- `solar-eclipse-alignment`: `view_mode: wide_alignment` 다음에
  `view_mode: earth_close_shadow_track`
- `lunar-eclipse-alignment`: `view_mode: wide_alignment` 다음에
  `view_mode: moon_close_shadow_entry`

컨트롤러가 사용됐는데 필수 비트가 없거나, 두 비트가 다른 씬에 있거나,
확대 비트가 먼저 나오거나, 두 구간 사이에 공백이 있으면 하네스 검증을
통과하지 못한다. 관측자 시점의 금환일식이나 붉은 달 같은 후속 비트는 이
필수 쌍을 대체하지 않는다.

시뮬레이션 시간은 되감지 않는다. 이전 상태를 증거로 다시 보여줄 때는 현재 시간을 되돌리지 말고 snapshot layer를 누적한다. 레이어는 후속 비트에서 자동으로 사라지지 않으며 제거가 필요할 때만 명시적 hide event를 쓴다. 겹친 컨트롤러가 같은 patch target을 쓰면 서로 다른 priority를 지정한다.

같은 프레임의 패치는 기본 시뮬레이션 상태, 축적 레이어, 엔티티 표현 오버라이드, 카메라 패치, 명시적 hide event 순서가 재현되도록 priority를 설계한다. 컨트롤러는 전체 장면을 교체하지 않고 자신이 소유한 patch만 반환해야 한다.

## 최종 점검

- `primary_route: local` 시퀀스만, 그리고 그 시퀀스를 정확히 한 번씩 포함한다.
- 각 scene span의 프레임, audio frames, tail silence의 산술이 정확하다.
- 모든 공통 local beat가 timeline에 존재하며 owning scene span 안에 있다.
- 식현상 컨트롤러의 wide→close 비트가 같은 씬에서 빈틈없이 순서대로 이어진다.
- scene graph와 controller 이름은 로컬 레지스트리에 실제로 존재하는 이름만 사용한다.
- 씬 경계에서도 geometry, entities, camera와 누적 layers의 상태가 이어진다.

새 주제는 [run 소스 계약](../../docs/run-render-sources.md)에 따라 `runs/<run>/scripts/`에
장면·계산·validator·전용 테스트를 작성한다. `simulation.json`의 `preset: run-scene`과
run 소유 JSON Schema를 사용하고 공용 등록 파일에는 주제 분기를 추가하지 않는다.
