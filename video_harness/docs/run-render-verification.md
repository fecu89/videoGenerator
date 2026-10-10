# 영상별 렌더 소스·Shadow Pool 변경 검증

2026-10-10, Blender 5.2.1에서 확인했다. 사용법은 [영상별 렌더 소스](run-render-sources.md)를 따른다.

## 구현과 호환 범위

- 새 영상의 장면·계산·검증·전용 테스트는 `runs/<run>/scripts/`, 자산은 `assets/`, 재생성할 중간물은 `.render-cache/`에 둔다. `render-source.json`이 실행할 코드와 의존 파일을 선언한다.
- Blender와 Three.js 모두 공용 주제 등록 없이 실행한다. 프리뷰·초본·최종본·대안 편집은 원본 run에서 소스를 찾는다. Blender MCP도 같은 스냅샷·템포·그림자 설정을 사용한다.
- 새 설정 v7의 `blender.shadow_pool_mb` 기본값은 2048이다. 설정 웹의 고급 옵션으로 바꾸며 실행 시작 시 `run-settings.json`에 고정한다. 실제 Scene 적용 실패는 오류로 처리한다.
- v6 이하 실행은 기존 설정 자료형으로 읽는다. 기존 v6 설정 해시와 파일 바이트 보존 검사가 통과했다. 이번 변경은 기존 `blender_renderer/` 파일을 수정하지 않는다.
- Three.js 공용 소스 변경은 기존 방식대로 renderer 해시를 바꾼다. 해당 기존 실행을 다시 제작할 때 프리뷰 재검토가 필요하다. 기존 run의 설정·승인·영상 파일을 자동으로 수정하거나 재렌더하지 않았다.
- 자동 커밋은 없다. Git에서 제외되는 run 원본은 별도로 백업해야 한다.

## 완료 기준별 증거

| 확인 사항 | 검증 |
| --- | --- |
| 일반 제작 전후 Git 상태 불변 | 실제 Blender로 서로 다른 두 run 생성 → 렌더 → 코드 수정 → 재렌더. 이미 존재한 staged/unstaged 변경까지 포함한 `git status --porcelain` 결과가 전후 동일 |
| 캐시 삭제 후 원본 보존 | `.render-cache/` 삭제 뒤 `scripts/` 원본 존재 확인 |
| A 변경이 B에 영향 없음 | A의 코드·GLB 바이트·simulation·설정을 각각 변경하면 A의 현재 프리뷰 승인은 실패하고, B의 renderer 버전과 승인은 그대로 유지 |
| 입력 무결성 | 누락·경로 이탈·선언되지 않은 entrypoint/import, 복사 중 변경, 스냅샷 변조를 거부 |
| 두 실행의 모듈·객체 격리 | 같은 이름의 Python 모듈을 분리하고, 실제 Blender 단일 프로세스에서 MCP 장면 두 개를 연속 준비해 논리 anchor 이름 보존 |
| Blender 2GB 적용 | 실제 렌더 보고서와 저장 후 다시 연 `.blend` 모두 2048. 새 설정으로 기존 내장 장면을 재사용하는 경로도 확인 |
| Three.js 소스 격리 | 두 새 graph의 실제 브라우저 렌더와 Python 호스트 경로 검사. 번들은 run 스냅샷에 생성되며 공용 `dist`는 변경되지 않음 |
| 제작 경로 일관성 | 별도 simulation 파일명과 캐시 재사용, 대안 편집의 run 템포, 초본 완료 직전 소스 승인 재검사 회귀 테스트 통과 |

## 512MB / 2048MB 비교

1920×1080에서 그림자를 만드는 area light 64개와 블록 36개로 구성한 동일 장면의 연속 5프레임을 비교했다. 기존 영상 대신 독립적인 검증용 run을 사용했다.

| 항목 | 512MB | 2048MB |
| --- | --- | --- |
| 실제 Scene·보고서 설정 | 512 | 2048 |
| `Shadow buffer full` | 발생 | 발생하지 않음 |
| 블록 주위 접촉 그림자 | 일부 누락 | 복원됨 |
| 연속 프레임 검토 | 누락 상태 확인 | 갑작스러운 전체 그림자 소실은 관찰되지 않음 |

64개의 개별 조명이 만드는 방사형 그림자 띠는 남는다. Shadow Pool 증설이 넓은 평면의 자기 그림자 오류까지 해결했다고 판정하지 않는다. 이 검사는 메모리 부족으로 인한 그림자 누락 개선을 확인한 것이다.

비교 이미지·`.blend`·로그·수치 보고서는 Git 제외 폴더 [`runs/_harness-verification-shadow-pool/`](../../runs/_harness-verification-shadow-pool/)에 보관한다. 상세 결과는 [`comparison-report.json`](../../runs/_harness-verification-shadow-pool/comparison-report.json)을 확인한다.

## 재검사 명령

```bash
python -m pytest -q video_harness/tests
VG_REAL_BLENDER=1 python -m pytest -q video_harness/tests/test_run_source_integration.py
VG_REAL_THREEJS=1 python -m pytest -q video_harness/tests/test_run_threejs_backend.py
npm --prefix video_harness/science_renderer run typecheck
npm --prefix video_harness/science_renderer run build
npm --prefix video_harness/science_renderer test -- --run
```

실제 Blender 검사 4개, 실제 Three.js 호스트 검사 1개, 제작 경로 회귀 검사 79개, TypeScript 검사 176개가 통과했다. TypeScript 타입 검사와 빌드도 통과했다.

전체 Python 결과는 **1,127개 통과, 23개 생략, 기존 실패 8개**다. 기준 코드에서도 재현한 다음 8개 실패는 이번 범위에서 유지한다. 기존 Blender 소스의 호환 해시를 바꾸거나 기존 실패를 숨기기 위해 검사를 완화하지 않았다.

| 기존 실패 | 내용 |
| --- | --- |
| `test_callout_policy` 3개 | `adiabatic.py`, `optical_depth.py`의 CalloutLayer 누락, `optical_depth_story.py`의 직접 텍스트 |
| `test_visibility_key_policy` 2개 | `energy_transport.py`, `optical_depth_story.py`의 visibility 키프레임 |
| `test_creative_gates` 2개 | 기존 오류 문구의 `검증 기록`과 테스트가 기대하는 `승인` 불일치 |
| `test_prompt_documents` 1개 | 기존 문서 테스트가 현재 M4A 전달 방식 대신 `final-en.mp4`를 기대 |

## 구현 중 판단

- Three.js는 공용 프레임 실행기에서 별도의 범용 run 브라우저 어댑터를 선택한다. 공용 주제 분기를 추가하지 않으며 기존 factory·상태·엔진 검사 계약을 유지한다.
- 기존 주제 코드의 자동 이전은 하지 않았다. 새 소스 경로와 그림자 메모리는 독립 fixture로 검증했으므로 기존 영상의 외관 개선까지 검증한 결과는 아니다.
- 기준 코드의 기존 실패 8개는 별도 유지보수 대상이다. 새 기능 검사와 기존 전체 검사에 새 실패가 생기는지 구분한다.

최종 별도 코드 검토의 중요 지적 4개(지속 MCP 세션의 객체 이름 충돌, 별도 simulation 경로, MCP·대안 편집 템포 전달, 초본 완료 시 승인 재검사)는 각각 재현 테스트를 추가하여 수정했다.
