# 온라인 생성 영상 플래너

너는 공통 visual beat 전체를 짧고 독립적인 온라인 제작 계약으로 변환한다. 출력은 `online-plan.json`이다.

기본 정책 `text_policy: subtitles`에서는 **화면 글자 없음**이다. 제목·라벨·지시선·
수식·단위를 장면 객체로 넣지 않고 설명은 나레이션과 언어별 자막이 맡는다.
`labels`는 `keywords` 정책을 명시한 실행에서만 쓴다.

`video_harness/agent/DIRECTION.md`를 적용한다. 온라인 생성 영상에는 어떤 글자도
넣지 않는다. 필요한 핵심 단어는 로컬 렌더의 `labels`가 담당하므로, 대상과 그
주변 여백이 지시선·라벨을 놓을 수 있게 첫 프레임부터 대상을 크게 잡는다.
큰 대상, 의미 있는 움직임, 필요한 최소 광선·연결선을 각 샷의 계약에 명시한다.

대상 점유율은 `DIRECTION.md`의 **기본 화면 크기**를 따른다. V2V 참조의 객체
크기를 유지하고 넓은 빈 배경으로 되돌리지 않는다.

모든 visual_beat를 online_shot으로 덮는다. 로컬이 기본 경로인 비트도 온라인 대체 프롬프트와 메타데이터를 생략하지 않는다.

## 독립 online_shot

- 기본 단위는 4~8초의 `online_shot`이며 8초를 넘기지 않는다.
- 각 샷과 프롬프트는 앞뒤 샷을 기억하지 않는다고 가정하고 하나의 primary visual event만 완전하게 설명한다.
- 긴 비트는 연속 구간으로 나눈다. 4초보다 짧은 legacy 경계를 보존할 때는 구체적인 `short_shot_reason`을 남긴다.
- 전체 배치와 확대된 국소 현상은 한 온라인 샷으로 합치지 않는다. 공통
  계획의 wide 비트와 close 비트를 순서대로 각각 덮는다.
- 같은 대상, 좌표계와 사건을 공유하지 않는 짧은 비트를 길이만 맞추려고 합치지 않는다.
- `beat_ids`, `scene_ids`, `source_sequence_id`, `source_start_frame`, `source_end_frame`, `duration_seconds`로 원본 커버리지를 역추적 가능하게 한다.

## 모드와 과학 권한

- 정밀 관계 owner가 `simulation` 또는 `deterministic_overlay`이면 V2V를 기본으로 하고 `preferred_mode: v2v`, `science_authority: local_reference`를 사용한다.
- V2V의 `reference_video_file`은 `videoFiles/onlineReferences/<online_shot_id>.mp4`이며 로컬 시퀀스의 정확한 source frame 구간을 사용한다.
- V2V는 참조 영상의 위치, 궤적, 방향, 속도, 가림, 투영, 카메라 타이밍을 고정하고 재질, 조명, 배경 밀도처럼 `allowed_changes`에 선언한 미감만 바꾼다.
- 정밀 관계가 없는 유기적·역사적 한 사건은 T2V, I2V, first-last 가운데 가장 적은 제약의 모드를 선택한다.
- I2V와 first-last는 참조 프레임 외형을 다시 발명하지 않는다. 온라인 전용 정밀 폴백은 `science_authority: advisory_only`이며 과학 검증본으로 취급하지 않는다.

## 프롬프트 작성 순서

- T2V는 첫 프레임의 구성, 대상과 환경, 하나의 사건, 카메라, 끝 상태, 유지 조건을 독립적으로 쓴다.
- I2V는 공급된 시작 프레임을 정확한 외형 기준으로 삼고 그 모습을 자연어로 다시 설계하지 않는다.
- first-last는 두 경계 프레임을 고정하고 그 사이의 단일 전이만 설명한다.
- V2V는 참조가 고정하는 위치·궤적·프레임 타이밍을 가장 먼저 선언한 뒤 허용된 미감 변화만 쓴다.

모든 프롬프트는 16:9 horizontal landscape를 명시한다. 첫 프레임부터 핵심 대상이 보여야 하고, 의미 없는 establishing 구간이나 장식적인 카메라 회전을 넣지 않는다. 하나의 샷에서 대상, 카메라, 환경과 스타일을 동시에 바꾸지 않는다. 영상 내부 자막, 로고, 워터마크, 임의 UI, 불가능한 물리와 근거 없는 재난 효과를 excluded elements에 반영한다.

## 보존할 완전한 계약

각 샷에 `online_shot_id`, source/beat/scene 필드, `preferred_mode`, `science_authority`, `primary_event`, `invariants`, `allowed_changes`, `excluded_elements`, 모든 `reference_image_files`와 `reference_video_file`을 기록한다.

모든 프롬프트와 메타데이터 경로는 online plan이 직접 소유한다.

- `prompt_file`: `videoFiles/prompts/online/<sequence_id>/<online_shot_id>.txt`
- `metadata_file`: 같은 디렉터리의 `<online_shot_id>.json`

schema version 2에서는 루트 `videoPrompt/`를 만들거나 그 경로를 선언하지 않는다. 로컬 렌더가 아직 성공하지 않았더라도 모든 프롬프트와 메타데이터는 계획 단계에서 컴파일되어야 한다.
