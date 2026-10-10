# Blender 렌더 경로

Python 하네스의 schema-v2 계획, 음성 길이 검증, 초안/최종 QA, FFmpeg 합본,
스테이징 후 공개 흐름을 유지하면서 Blender EEVEE를 렌더러로 선택할 수 있다.
별빛의 `stellar-spectra-blender-v1`과 식현상의
`sun-earth-moon-blender-v1`, 와도의 `vorticity-blender-v1` 그래프를 지원한다. 다른 과학 주제는 해당
장면 그래프와 컨트롤러 구현을 추가해야 한다.

## 사용

```bash
python -m video_harness blender status --port 9876
python -m video_harness plan-video runs/<run>
python -m video_harness blender prepare runs/<run> --port 9876
```

`status`는 열린 Blender의 버전, 실행 파일, 현재 프로젝트를 읽는다.
`prepare`는 유효한 음성과 네 계획을 확인하고 MCP를 통해 별도 Scene을 추가한다.
기존 Scene을 삭제하지 않으며 `blender/SEQ01-editable.blend`에 복사본을 저장한다.
파일이 이미 있으면 덮어쓰지 않고 실패한다. 이 명령은 렌더링하지 않는다.

대본·음성 확정 후 영상 아이디어를 바탕으로 계획을 작성하고 중간 영상대본 승인 없이 프리뷰 검토 웹까지 연다.

```bash
python -m video_harness preview runs/<run>
# 웹에서 프리뷰 승인 후:
python -m video_harness produce runs/<run> --quality draft
```

`produce`의 Blender 렌더는 별도 백그라운드 프로세스에서 수행한다. 데스크톱의
프로젝트를 렌더 중에 바꾸지 않으며 긴 작업으로 MCP를 점유하지 않는다.
데스크톱에서 수동 수정한 `.blend`는 자동 렌더 입력이 아니다. 재현 가능한
계획과 네이티브 장면 구현을 입력으로 다시 구성한다.

## 계획 계약

`local-sequence-plan.json`의 최상위에 `"renderer": "blender"`를 선언한다.
생략된 기존 실행은 `threejs`를 사용한다. Blender 선택은 계획 해시에 포함된다.

혼합 제작에서는 각 `sequences[]` 항목에 `renderer: "blender"` 또는
`renderer: "threejs"`를 선언한다. 생략하거나 null이면 계획 최상위 renderer를
상속한다. Python은 시퀀스별로 렌더러를 선택하고 같은 해상도/FPS의 MP4와
음성 타임라인을 합친다. `.blend` 파일은 Blender 시퀀스에만 요구한다.
각 시퀀스의 실제 backend 기록과 QA는 그대로 유지한다.

별빛 도표의 Three.js 그래프는 `stellar-spectra-threejs-v1`이다. 분광, 흡수선
탐색, 원소 비교, 고온/저온 수소선, OBAFGKM 배열, G0~G9 세분을 지원한다.
Blender는 별 표면·거리·항성 대기·O/M 비교·태양 장면에 사용한다.
`blender prepare`는 혼합 계획 안의 Blender 시퀀스만 각각 저장하며 렌더하지 않는다.
두 렌더러의 소스 코드와 Blender 이미지 자산은 캐시 버전에 반영된다.

### 장면 전환

새 연속 장면은 [대상을 이어가는 전환](continuous-transitions.md)에 따라
같은 객체와 공통 시간으로 구현한다. 전체를 확대해 내부를 드러내고, 한 단위를
유지한 채 주변 단위가 집결하거나, 앞 대상이 빠지는 동안 다음 대상이 들어온다.
씬 번호에 따라 전체 객체를 교체하지 않는다. 실제 객체·카메라 상태를 캡처하고
전환 전·중·후 프레임을 직접 검토한다.

결합 구조의 `bonding-flow-blender-v2`는 `bonding-blender` 프리셋과
`blender_renderer/bonding_flow.py`의 `BondingFlowGallery`를 사용한다.
`build()`로 구성한 객체를 재사용하고 `sample(frame)`에서 공통 시간의 상태를
결정론적으로 계산하며 `bake()`로 변환·곡선·재질 키프레임을 저장한다.
이 그래프의 10개 장면 순서와 연속 시간축 검사는 해당 예제 전용이다.

식현상 그래프의 beat에 `controller_options.continuous_space: true`를 지정하면
`eclipse_continuity.py`의 공유 공간 연출을 사용한다. 2→3→4는 절대 나레이션
시간으로 같은 태양·달·지구와 원근 카메라를 구동하므로 렌더 시퀀스 경계에서도
동선이 이어진다. 7→8은 같은 달과 그림자 진행을 확대하고, 10→11은 처음부터
5도로 기울어진 궤도를 다른 시점에서 관찰한다. 독립된 설명은 컷을 유지한다.
카메라 투영 방식·초점거리·재질 페이드도 네이티브 키프레임으로 저장한다.

이 연출의 태양–지구–달 공간 배치는 축약 모형이다. 400배라는 실제 수치는
화면에 `실제 지름`, `실제 거리`로 제시하고 공간 배치의 축약 여부를 함께
표시한다. 배치의 화면상 길이를 실제 거리 비율로 읽으면 안 된다.

별도의 편집 효과가 필요한 경우 각 timeline beat의 `controller_options.entry_transition`에
`{"style":"smoothleft","duration_seconds":0.45}`를 지정할 수 있다.
지원 효과는 `fade`, `smoothleft/right/up/down`, `circleopen`, `zoomin`이다.
지정하지 않은 기존 계획은 원래 동작을 유지한다.
이 효과는 같은 객체의 확대·분리·집결 동작을 대신하는 연속성 구현이 아니다.

Python이 렌더된 PNG에 FFmpeg 전환을 합성한 뒤 MP4를 인코딩한다. 직전
장면의 마지막 프레임에서 새 장면의 움직이는 첫 프레임들로 전환하므로 전체
프레임 수, 씬 경계와 음성 시작점은 바뀌지 않는다. 시퀀스가 달라도 연결하며,
직전 PNG 캐시가 없으면 저장된 마스터의 마지막 프레임을 사용한다.
효과는 최대 1초이며 짧은 beat에서는 해당 beat 길이로 제한한다.

합성된 프레임은 PNG 내용까지 포함한 상태 지문과
`editorial_transition:<style>` 기록을 갖는다. 실제 렌더러 정보는 유지한다.
이 전환은 Python 합성 단계이므로 `.blend` 자체에는 들어 있지 않으며,
씬별 MP4·전체 MP4·QA 프레임에는 동일하게 반영된다.
현재 전환 합성은 기본본 제작 경로에 적용한다. 별도 카메라 override를 다시
렌더하는 추가 variant 경로에는 아직 적용하지 않는다. 이번 실행은 저장된
`balanced_only` 설정으로 기본본을 제작한다.

별 표면은 `blender_renderer/assets/stellar-photosphere-v2.png`의 생성 이미지를
구에 입혀 표현한다. 생성 방식과 프롬프트는 같은 폴더 README에 기록한다.
화면에는 개념 모형 문구를 넣지 않으며 과학 모형의 한계는 이 문서와 실행
폴더의 research.md에 기록한다.

- 그래프: `stellar-spectra-blender-v1`
- render mode: `simulation`
- simulation.json preset: `stellar-spectra-blender`
- physics.model: `schematic-stellar-spectra`
- 스키마: `schemas/spectral-simulation.schema.json`
- 컨트롤러: `blender_renderer/spectra.py`의 `CONTROLLERS`
- 해상도와 FPS: 기존 계획의 defaults 및 실행별 run-settings.json
- variant_mode: 기존 설정 사용. 이번 실행은 balanced_only이며 네 레시피 계약은 유지.

한 시퀀스의 모든 설명 패널을 하나의 네이티브 Blender Scene에 배치한다.
컨트롤러는 카메라를 연속적으로 이동시키고 별, 스펙트럼, 원자 모형 및
곡선 표식을 움직인다. 씬 경계에서 검은 화면을 넣지 않는다. 0부터 시작하는
반개구간 canonical frame은 Blender의 1부터 시작하는 프레임에 `+1`로 대응한다.
초안 프레임은 기존 하네스와 같은 정수 내림 매핑을 사용한다.

## 산출물과 검증

- `videoFiles/sequences/{draft,final}/SEQ01.blend`: 실제 렌더 장면과 키프레임, 패킹한 글꼴
- 기존 경로의 MP4, 씬별 클립, 온라인 V2V 참조, 접촉 시트, QA 보고서
- 프레임별 실제 카메라·객체 변환·흡수선 재질값으로 계산한 상태 지문
- `backend.actual=blender_eevee`와 Blender 버전 기록
- Blender Python 오류를 0이 아닌 종료 코드로 전달하고 누락/빈 프레임을 거부
- 코드와 Blender 실행 파일 변경을 반영한 렌더 캐시 지문

### 편집용 키프레임 굽기

`.blend`에 모든 프레임을 키로 남길 때 프레임마다 `keyframe_insert`를 부르지
않는다. 키 하나를 넣을 때마다 커지는 F-커브 전체가 복사되어 비용이 프레임 수의
제곱으로 늘어난다. 2026-09-24 와도 영상(객체 228개, 7346프레임)에서는 이 단계만
1.5시간을 넘겼다. 첫 프레임만 `keyframe_insert`로 채널을 만들고, 이후 프레임은
`sample(frame)` 값을 모아 채널마다 `keyframe_points.add` + `foreach_set('co', …)`로
한 번에 쓴다(Blender 5의 슬롯 액션은 `bpy_extras.anim_utils.action_get_channelbag_for_slot`).
같은 결과를 140초에 굽는다. 참조 구현: `vorticity_story.py`의 `bake()`. 새 렌더러는
이 방식을 따르고, 굽기 뒤 표본 프레임에서 키 재생 결과와 `sample()`이 일치하는지 확인한다.

### 표시·숨김은 키프레임으로 만들지 않는다

이동 키와 `hide_render`/`hide_viewport` 키를 함께 가진 객체가 있으면 EEVEE가
렌더할 때마다 장면을 통째로 다시 동기화한다. 2026-09-26 유령정체 영상(객체 626개)에서
384×216 초본 한 장이 약 2.3초 걸렸고, 표시 키만 없애자 약 0.5초가 되었다. 카메라
렌즈 키나 재질 소켓 키는 원인이 아니었다. 해상도가 오르면 차이는 더 커진다.

- 무대 밖 객체는 카메라에 보이지 않는 곳(예: 지면 아래)으로 옮긴다. 이동 키만 남는다.
- 나타남·사라짐은 `fade_material`의 불투명도 소켓(`animated_sockets`)으로 표현한다.
- `insert_keys`에 `hide_render`/`hide_viewport`를 넣지 않는다.
  `tests/test_visibility_key_policy.py`가 새 갤러리에서 이를 막는다. 목록에 있는
  기존 갤러리는 승인된 렌더러 해시 때문에 그대로 두며, 같은 이유로 느릴 수 있다.

### 넓은 바닥은 그림자를 드리우지 않는다

해가 비스듬한 장면에서 아주 큰 평면(유령정체 영상의 잔디는 18 km 사각형 하나)이
그림자를 드리우면, 평면이 자기 자신을 가리는 것으로 계산되어 가까운 바닥에 대각선
줄무늬와 거뭇한 얼룩(shadow acne)이 생긴다. 초본 해상도에서는 흐릿한 얼룩으로만
보여 놓치기 쉽다. 바닥·도로·차선처럼 평평한 면은 `visible_shadow = False`로 두고,
그림자를 받는 것은 그대로 둔다. 차처럼 그림자를 드리워야 하는 물체는 영향이 없다.
새 장면은 대표 프레임 하나를 720p 이상으로 렌더해 바닥 질감을 확인한다.

렌더 시간을 비교할 때는 실제로 굽은 장면에서 측정한다. 1프레임에만 키를 넣고
다른 프레임을 렌더하면 모든 객체가 그 키 값으로 되돌아가 엉뚱한(대개 가벼운) 화면을
렌더하므로 결과를 믿을 수 없다. 워커가 저장한 `scene.blend`를 열어 `frame_set` 뒤
`bpy.ops.render.render`만 재면 단계별 비용을 분리할 수 있다.

관측 자료를 재현한 스펙트럼이 아니라 교재의 관계를 설명하는 **개념 모형**이다.
흡수선 위치는 클래스 사이에서 고정하고 밝기만 바꾼다. 원소의 선 세기 곡선은
정성적 근사이며 수소선의 A형 최대와 고온/저온 양쪽 감소를 표현한다.
중성 원자와 이온, 분자를 구별하되 정확한 항성 대기 모델의 수치로 해석하지 않는다.

## 설치 및 테스트

macOS 기본 실행 파일은 `/Applications/Blender.app/Contents/MacOS/Blender`다.
다른 위치는 `VG_BLENDER_BINARY`로 지정한다. 네이티브 장면의 한글 글꼴은 현재
macOS `AppleGothic.ttf`를 사용한다. FFmpeg와 FFprobe는 기존 하네스와 같다.
Blender 5.2.1 LTS에서 검증한다. MCP 통신은 HTTP가 아니라 NUL 종료 JSON TCP다.
발광 재질 중심의 도식은 EEVEE 8 samples로 렌더한다. 1080p의 별·분광형 배열
장면에서 기본 64 samples와 비교해 선과 글자의 가독성을 확인했다.

```bash
python -m pytest -q video_harness/tests/test_blender_backend.py -p no:cacheprovider
VG_REAL_BLENDER=1 python -m pytest -q video_harness/tests/test_blender_backend.py -k native -p no:cacheprovider
```

네이티브 테스트는 임시 폴더에서 짧은 합성 입력을 렌더하며 사용자 실행의
영상 생성대본 승인을 대신하지 않는다.

최종 QA/산출물 검증에 실패하면 `.local-final-*` 작업 폴더를 보존한다.
공개 단계에서도 원본을 복사해 사용하므로 실패 후 렌더 결과와 캐시를 복구할 수 있다.
성공한 작업 폴더만 정리하며 기존 공개본 롤백 규칙은 유지한다.

### 별에서 지구까지 후퇴하는 장면

`spectra-distance` beat에 `controller_options.distance_flight: true`를 주면
기존 망원경 도표 대신 원근 카메라의 후퇴 장면을 만든다. `flight_path.py`는
느린 출발·급가속·감속의 연속 경로를, `distance_flight.py`는 표면 이미지가
있는 별, 스쳐 가는 별의 시차와 잔상, 지구 전경을 구성한다. 단위와 이동
시간은 연출용으로 압축한 값이며 실제 항성 간 거리나 광속을 재현하지 않는다.

지구 텍스처는 `assets/earth-atmos-r160.jpg`로 패킹한다. 원본 URL과 라이선스는
같은 폴더의 README 및 `earth-texture-license.txt`에 있다. 지구 뒤에 도착하면
같은 별이 작은 광점으로 남으며, 지구가 그 별을 가리지 않도록 구도를 잡는다.
혼합 타임라인의 카메라 변경은 Blender의 카메라 마커로 저장한다.

## Continuous optical journey (review v5)

Two opt-in controller options extend the native renderer without changing existing jobs:

- `continuous_intro_flight: true` on the opening timeline makes `spectra-intro` and `spectra-distance` share a `DistanceFlight` star and perspective camera. `opening_motion.py` defines the final camera position and text-only opacity fade. No crossfade is applied at this beat boundary.
- `optics_journey: true` uses `OpticsJourney` for `spectra-dispersion`, `spectra-temperature-question`, `spectra-atmosphere`, and `spectra-elements`. These beats share their star and spectral panel, then move into a magnified atmosphere and H/He comparison. Their internal boundaries use object/camera motion rather than frozen-frame transitions.

`animated_materials.py` exposes opacity/twinkle sockets for keyframing and frame-state fingerprints. Saved `.blend` files include those material animations. Spectrum line positions remain fixed while their contrast changes. New comparison panels use selected NIST H I / He I wavelengths; intensities and geometric scales are illustrative. The existing controllers retain their original behavior unless an option is enabled.

## 태양·지구·달과 식현상

- 그래프: `sun-earth-moon-blender-v1`
- simulation preset: `sun-earth-moon-blender`
- physics.model: `finite-disk-eclipse-teaching-model`
- 구현: `blender_renderer/eclipse.py`, 기하 계산·입력 검증: `eclipse_math.py`
- 컨트롤러: `eclipse_math.CONTROLLERS`

일식·월식 관측 원반, 지름과 거리의 약 400배 관계, 일식 정렬과 지구 표면
그림자, 본그림자/반그림자의 관측 차이, 금환일식, 월식 진입, 붉은 달,
대기 광선, 월 공전과 약 5도 궤도 기울기를 구성한다. 정렬과 그림자 근접은
같은 컨트롤러의 인접 beat로 연결하며 `view_mode`로 전체/근접을 구별한다.

전체 정렬은 압축된 교육 모형이다. 유한한 원반 광원과 실제 구면으로 그림자를
만들며, 발광 태양 외관이 자체 광원을 막지 않도록 물리 천체만 shadow linking에
포함한다. 관측 월식의 색과 경계는 별도 투영 모형이다. 대기 광선도 실제
대기 굴절률 분포를 계산한 광선 추적이 아닌 대표 경로다. EEVEE 16 samples를 쓴다.

궤도 모형은 지구 반지름 0.1, 달 반지름 0.0273, 달 공전 반지름 6, 기울기
5도를 쓴다. 전체 화면의 확대 위치 표시는 별도 발광 천체이며 물리 그림자를
만들지 않는다. ‘천체 크기 확대’로 구별하고 근접 시 숨긴다. 확대에 따라
안내선 굵기를 조절한다. 카메라는 화면 위쪽 기준을 명시해 롤이 뒤집히지 않는다.

대표 프레임·전환·글자 투영 경계를 확인하고 전체 렌더를 실행한다. 실제 생성한
`.blend`에는 카메라, 객체, 월식 재질값, 경로와 선 굵기의 키프레임이 포함된다.

일식 관측 원반의 북반구 기본 방향은 `northern_solar_offset()`이 계산한다.
천구 북쪽을 위에 두고 달이 오른쪽(서쪽)에서 왼쪽(동쪽)으로 태양에 진입한다.
천체 원반 애니메이션만 수정하며 글자나 월식 원반을 통째로 반전하지 않는다.

## 유령정체(원형 트랙 교통)

- 그래프: `phantom-jam-blender-v1`, preset: `phantom-jam-blender`
- 구현: `phantom_jam.py`, 교통 모형·시간 변환·카메라 및 작업 검증: `phantom_jam_math.py`
- 컨트롤러: `phantom-jam`, `controller_options.beat_number`로 승인된 17개 비트를 선택한다.
- `style.asset_root`의 `generic_passenger_car_pack.glb`에서 차체 9종(쿠페 제외)과 바퀴를
  가져와 85%로 줄인다. 차의 앞은 원본 차체 노드의 −Z, 위는 −Y다.

차의 위치·속도는 최적 속도 차량 추종 모형(dv/dt = a(V(h) − v))을 한 번 적분한 결과다.
둘레 230 m, 22대에서 정체 한 덩어리(멈춘 차 5~6대)가 시속 약 23 km로 뒤로 이동한다.
결과가 작은 사건의 크기에 민감하므로 한 덩어리 정체와 첫 정지 위치를
`tests/test_phantom_jam.py`로 고정했다. 계획의 simulation_time은 영상 시간이며,
모형 시간 변환(시간 건너뛰기·빠른 화면)은 계산 모듈 안에서 부드럽게 처리한다.

## 와도·관람차·위도와 로스비파

- 그래프: `vorticity-blender-v1`, preset: `vorticity-blender`
- 구현: `vorticity.py`, 계산 및 작업 검증: `vorticity_math.py`
- 컨트롤러: `vorticity-flow`, `vorticity-wheel`, `vorticity-earth`, `vorticity-wave`
- `controller_options.scene_number`로 승인된 19개 설명 단계를 선택한다.
- `style.asset_root`는 실행 폴더의 GLB 사본 디렉터리다. 지구와 관람차를 가져오며, 관람차 객실의 원본 자세 유지 애니메이션을 월드 변환으로 샘플링한다.

북반구 평면 도식은 X 동쪽, Y 북쪽, Z 관측자 방향이다. `planetary()`는
f=2Ωsinφ를, `relative()`는 일정 두께·마찰 없는 모형의 ζ=f(초기 위도)-f(현재 위도)를
계산한다. 북극 지표에 정지한 공기와 40도에서 이동한 공기는 별도 사례이며,
`contributions()`가 초기 조건을 구분한다. 막대의 길이는 Ω=1로 정규화한
설명용 값이다. 그림의 길이·시간은 실제 기상 자료를 재현하지 않는다.

흐름 도식은 입자 이동과 국지 회전의 연결을 설명하며, 로스비파 분산 관계를
수치 적분한 예보가 아니다. 구면 자전·지역 연직축과 공기 표식을 같은 변환으로
처리한다. 지표 관측 구간은 명시적으로 정지 상태를 유지하는 비교 장면이다.

사용자 승인을 받은 영상 계획은 변경하지 않고 네이티브 구현을 수정할 수 있다.
시각 사건·관측 기준·장면 순서가 바뀐다면 기존 승인 규칙을 다시 따른다.
대표 프레임은 Blender MCP로 검토하고 긴 전체 렌더는 별도 Blender 프로세스로
실행해 데스크톱 작업을 점유하지 않는다.

## 새 장면 코드와 Shadow Pool

새 장면은 공용 `blender_renderer/`에 추가하지 않고 [run 소스 계약](run-render-sources.md)을
따라 `runs/<run>/scripts/`에 작성한다. 프리뷰·초본·최종본·대안 편집·MCP는 동일한
snapshot과 설정을 사용한다. 원본 run과 `.local-*` 출력 staging 경로는 분리된다.

새 설정 v7의 `blender.shadow_pool_mb`는 2048MB(2GB)가 기본이며 설정 화면의
고급 옵션에서 바꾼다. Blender 5.2.1에서 지원하는 16·32·64·128·256·512·1024·1536·2048MB만
허용한다. 적용값은 `frame-report.json`의 `blender_settings.shadow_pool_mb`에 기록하고
저장한 `.blend`의 `scene.eevee.shadow_pool_size`와 일치해야 한다. 지원하지 않는
Blender 버전이나 값은 오류로 중단한다. 기존 v6 이하 실행을 자동 갱신하지 않는다.

`Shadow buffer full`과 함께 그림자가 누락되면 Shadow Pool 부족을 먼저 확인한다.
넓은 평면의 줄무늬·자기 그림자 오류는 용량 부족과 별개다. 광원·접촉면·표면 분할·
그림자 해상도를 살펴보고, 2GB 적용만으로 해결됐다고 보고하지 않는다. 같은 연속
프레임을 최종 해상도에서 512MB와 2048MB로 비교하여 누락·깜빡임·줄무늬와 로그를
각각 확인한다.
