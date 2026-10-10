# 영상별 렌더 소스

새 주제의 장면·물리 계산·검증 함수·전용 테스트는 `runs/<run>/scripts/`에 작성한다.
공용 렌더러 등록, 주제별 분기, 공용 테스트를 새 영상 때문에 추가하지 않는다.
공통 엔진이나 QA의 실제 기능을 바꿀 때만 하네스를 수정한다.

```text
runs/<run>/
  render-source.json
  run-settings.json
  simulation.json
  scripts/
    scene.py                  # Blender 장면 (Three.js는 scene.ts)
    physics.py                # bpy 없는 host 입력 검사
    simulation.schema.json    # 이 영상의 simulation 입력 계약
    test_physics.py            # 이 영상만의 검사
  assets/                     # GLB, 텍스처, 출처
  .render-cache/
    source-snapshots/<hash>/   # 선언한 입력의 검증된 복사본과 번들
    sequences/                # 다시 생성할 수 있는 렌더 중간물
```

`scripts/`, `assets/`, manifest, 대본·계획·설정·승인·음성·최종본은 원본이다.
Git에서 제외되므로 run 전체를 별도로 백업한다. `.render-cache/`만 지워도 원본은
남고 다시 렌더할 수 있다. 영상 제작 뒤 Git 커밋을 요구하지 않는다.

## 소스 선언

영상 계획의 첫 프리뷰 전에 `render-source.json`을 작성한다.

```json
{
  "schema_version": 1,
  "simulation_schema": "scripts/simulation.schema.json",
  "graphs": {
    "my-video-v1": {
      "engine": "blender",
      "entrypoint": "scripts/scene.py:Gallery",
      "validator": "scripts/physics.py:validate_job",
      "source_files": ["scripts/scene.py", "scripts/physics.py"],
      "assets": ["assets/model.glb"]
    }
  }
}
```

`local-sequence-plan.json`의 `scene_graph`에 `my-video-v1`, `renderer`에 `blender`를
쓴다. 여러 graph나 Blender·Three.js를 한 실행에서 함께 사용할 수 있다.
사용하지 않는 자산은 선언하지 않는다. Python/TypeScript의 상대 import 대상도
모두 `source_files`에 선언한다. Python은 `from .physics import ...`처럼 상대
import를 사용한다. 경로는 run 내부의 `scripts/`·`assets/`에 있어야 한다.
절대경로, `..`, run 밖으로 나가는 심볼릭 링크, 선언하지 않은 entrypoint는 거부한다.
코드는 신뢰하는 제작자가 작성하며 소스 로더는 권한을 제한하는 샌드박스가 아니다.

`python -m video_harness render-source runs/<run>`은 코드 실행·스냅샷 생성 없이
선언, 파일, 해시를 출력한다. 잘못된 manifest는 기존 렌더러로 대체하지 않고 실패한다.
manifest가 없거나 해당 graph 항목이 없을 때만 기존 등록 경로를 사용한다.

## simulation과 host 검사

새 주제의 `simulation.json`은 `preset: "run-scene"`을 사용한다.
`schema_version: 1`, 기존 `output` 규격, `physics`·`style` 객체,
`scenes: [{"scene_id": 1}, ...]`를 둔다. scene ID는 승인된 대본과 정확히 같아야 한다.
선언한 JSON Schema는 simulation 전체를 검사하며 내부 `$defs`·`$ref`를 사용할 수 있다.
영상별 파라미터와 과학적 제약은 이 schema와 `validate_job(job)`에 구현한다.
validator는 순수 Python으로 작성하여 bpy·음성 모델 없이 실행되어야 한다.

## Blender 계약

```python
from render_runtime.blender_base import BlenderGalleryBase
from .physics import position_at

class Gallery(BlenderGalleryBase):
    def build(self):
        # bpy로 객체를 한 번 만들고 self.animated에 검토 대상을 넣는다.
        ...

    def sample(self, canonical_frame):
        # 순서와 무관하게 같은 프레임은 같은 상태가 되어야 한다.
        # job['physics'], job['style'], job['timeline'], job['assets'] 사용.
        ...
        return self.job['canonical_state_cache'][canonical_frame], self.animated

    def bake(self):
        # 편집 가능한 .blend가 필요하면 이 영상의 키프레임을 굽는다.
        ...
```

베이스는 Scene·camera와 `material`, `link`, `rect`, `path`, `ring`을 제공한다.
`link`는 Blender가 붙이는 `.001` 접미사와 별개로 논리 이름을 보존한다. bpy 연산자나
GLB import로 만든 객체는 `self.register_object("논리이름", obj)`로 등록하여 MCP의
여러 장면에서도 같은 anchor와 continuity ID를 사용한다.
화면 글자는 계획의 `labels`와 공용 `CalloutLayer`로만 표시한다. 베이스는
`build()` 뒤 labels를 실제 객체 이름에 바인딩하며, worker는 렌더마다 갱신한다.
직접 `text()`를 호출해 설명을 추가하지 않는다. 기존의 큰 글자 규격을 유지한다.
베이스를 상속하지 않아도 `scene`, `camera`, `bake()`, `sample(frame)` 계약은 같다.
asset은 `job['assets']['assets/model.glb']`처럼 스냅샷 경로로 읽는다.

공통 worker가 장면 생성·bake 후, `.blend` 저장과 PNG 렌더 전에 실제 Scene에
실행 설정의 EEVEE Shadow Pool을 적용한다. 지원하지 않는 값이나 적용 실패는
오류다. `frame-report.json`의 `blender_settings.shadow_pool_mb`에 실제값을 남긴다.
MCP `blender prepare`, 프리뷰, 초본, 최종본, 대안 편집은 같은 소스와 설정을 쓴다.

## Three.js 계약

manifest의 engine을 `threejs`, entrypoint를 `scripts/scene.ts:createRunSequence`로
선언한다. validator는 동일한 순수 Python 함수다.

```typescript
export function createRunSequence(job, api) {
  const {THREE, CalloutLayer, captureContinuity, stateFingerprint} = api;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, job.output.width / job.output.height, .1, 100);
  return {
    scene, camera,
    renderFrame(outputFrame) { /* 공통 canonical 시간으로 평가 */ },
    stateSnapshot() { /* SequenceStateSample 계약을 반환 */ },
  };
}
```

`RunSequenceRenderJob`, `RunSequenceRuntime`, `RunSourceApi`의 계약은
`science_renderer/src/render-job.ts`·`run-source-loader.ts`에 있다. 번들은 snapshot의
`build/`에 생성되고 자산은 `job.run_source_asset_urls`의 data URL로 전달된다.
실제 객체의 continuity와 fingerprint, WebGL 엔진 attestation은 공통 실행기가 수집한다.
Three.js run에는 공용 `sequence-registry.ts` 등록을 추가하지 않는다.

## 캐시와 승인

활성 graph의 선언·실제 코드·asset 바이트·simulation·run 설정·공통 runtime을 해시한다.
Blender는 바이너리 경로·수정 시각과 실제 Shadow Pool 설정도 포함한다.
다른 run의 새 코드나 GLB 추가는 이 해시에 포함되지 않는다. 입력을 복사한 뒤
해시를 다시 검사하며, 렌더 전후 원본이나 복사본이 바뀌면 결과를 인정하지 않는다.
수정한 run은 프리뷰를 새로 만들고 현재 프리뷰 승인을 받아야 한다.

기존 v6 이하 설정은 기존 자료형으로 읽는다. 기존 Blender worker·장면 파일·v1
해시는 그대로 유지한다. 새 v7 실행은 내장 장면을 재사용해도 새 공통 worker가
2GB를 적용한다. Three.js 공통 런타임 변경은 기존 정책대로 renderer 해시를
바꾸므로 해당 기존 실행은 다음 제작 시 프리뷰를 다시 검토한다. 기존 승인 파일을
자동으로 수정하거나 기존 실행을 재렌더하지 않는다.
