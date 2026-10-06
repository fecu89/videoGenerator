# Render-performance diagnostics

Performance measurement is an operator diagnostic, not a cache override.
Production defaults to attested SwiftShader because the measured
Metal-versus-SwiftShader SSIM/PSNR result did not clear the configured H.264
encode baseline. Metal remains fully selectable with
`renderer_backend: "metal"` for explicit render jobs and benchmarks. Every
request, including the default, must match `backend.actual`; a mismatch fails
instead of publishing a plausible-looking fallback render.

Each successful video-producing `produce` invocation (`all` or `video_only`)
atomically writes `render-performance.json` next to its other run reports.
`prompts_only` deliberately has no renderer and does not write the performance
report. It records these independently useful facts:

| Field | Meaning |
| --- | --- |
| `phase_events` | Individual measured intervals with labels such as sequence, quality, concat mode, and variant ID. |
| `phase_totals_ms` | Sum of events by phase name. Totals overlap when a parent phase contains child telemetry, so they are a bottleneck breakdown, not values to add into a wall-clock total. |
| `output_totals_ms` | End-to-end wall intervals keyed as `base:draft`, `base:final`, or `variant:<id>`. Base totals include their render and QA; variant totals include assembly and QA. |
| `output_frame_counts` | Rendered/reused frame counts and contributing sequence IDs keyed as `base:draft`, `base:final`, or `variant:<id>`. This is the direct per-output attribution source. Missing on a legacy report defaults to an empty mapping. |
| `renderer_reports` | Per-renderer browser version, `backend.requested` / `backend.actual`, vendor/renderer identity, capture method/mode, `capture_transport_bytes`, initialization, render, split capture/transfer, write, and total timings. |
| `rendered_frame_count` / `reused_frame_count` | Backward-compatible cumulative frames rendered or reused across every materialized base and variant output in the recorder. |
| `rendered_sequence_ids` / `reused_sequence_ids` | Stable sorted unique sequence IDs participating in those cumulative rendered/reused counts. |
| `avoided_copy_files` / `avoided_copy_bytes` | Regular files and bytes kept at their source paths rather than copied into each variant workspace. |

`timings.capture_ms` remains the backward-compatible aggregate of
`canvas_encode_capture_ms` and `browser_to_node_transfer_ms`. For the selected
`data-url-png` path, canvas PNG encoding is timed inside the browser and the
transfer field measures the remaining Playwright serialization plus Node
materialization/Base64 decode before the atomic file write. Playwright does
not expose an internal split for `locator-png`; its report therefore uses
`capture_timing_mode=playwright_combined`, records the complete screenshot API
boundary in `browser_to_node_transfer_ms`, and records `0` for the separately
unobservable canvas component. Legacy reports default the new timings to `0`,
the browser version to `unknown`, and the mode to `legacy_combined`.

`ffmpeg_decode` events are nested inside `qa` for black-frame scans, preview
extraction, boundary hashes, and contact sheets. They time the complete FFmpeg
decode/filter/output subprocess for that operation, so they intentionally
overlap the enclosing QA total and are not added to it.

Read a final-only frame subtotal directly from `output_frame_counts`, excluding
`base:draft`; do not infer it from timing labels. For the approved sample the
rendered subtotal is `base:final` plus its four final variants:
`2286 + 0 + 1393 + 463 + 204 = 4346`. The corresponding keys are
`base:final`, `variant:balanced`, `variant:explain`, `variant:dynamic`, and
`variant:cinematic`.

Canonical renderer frames remain PNG. This is intentional: PNG keeps a
lossless, inspectable frame boundary for deterministic hashes and subsequent
H.264 encoding. The production capture method is the benchmark-selected
`data-url-png`; `locator-png` remains an explicit diagnostic capture method,
not a silent fallback.

## Determinism and visual QA

Use a bounded, disposable benchmark root for renderer comparison:

```bash
python -m video_harness benchmark-render runs/<run> \
  --sequence SEQ01 --frames 120 --report /tmp/render-benchmark.json
```

The command verifies **same-backend exact determinism** first: two explicit Metal runs
must have identical decoded RGBA hashes and state fingerprints. That result is
the cache gate. It separately measures SwiftShader-versus-Metal **SSIM/PSNR**
cross-backend QA against the H.264 encode baseline; visual similarity never
makes a cross-backend cache entry eligible. Read the attestation in each
benchmark renderer report before interpreting timing or quality numbers.

Final media QA remains independent of these renderer checks: inspect the
published QA status, decoded duration/frame count/dimensions/audio, final
artifact hashes, and sequence-boundary findings. Boundary QA decodes the
frames around each half-open boundary and rejects an undeclared repeated
outgoing image across the incoming boundary.

## Concat and variants

Concat starts with MP4 stream preflight. Compatible inputs use
`mode=stream_copy`. An incompatible codec, dimensions, FPS, pixel format,
time base, or required audio stream takes the explicit **concat normalization
fallback**: the inputs are normalized to the first input's declared stream
spec, re-probed, and only then stream-copied. Every base and variant concat
attaches the shared recorder. Its `concat` phase event exposes `mode`,
`mismatched_fields`, and `normalized_inputs`; variant events additionally name
`variant_id` and `output_kind` (`silent` or `narrated`). A successful report
therefore cannot hide a variant `normalized_reencode` fallback.

Variant overrides were already selective: only the sequences an override
changes are rendered. For unchanged sequences the current assembler references
the original artifact root while it assembles the variant, rather than copying
base MP4s, frame reports, scene slices, and canonical state cache into the
workspace. The avoided-copy fields quantify that saved I/O. Reuse still
requires the normal input fingerprint/cache validation; a timing report cannot
relax it.

## Cumulative A--D interpretation

For a fair end-to-end comparison, make a read-only copy of the approved sample
run into a distinct temporary root for every configuration, retain identical
input/settings hashes, and record wall time outside the phase recorder:

| Configuration | Backend | Capture | Variant artifacts |
| --- | --- | --- | --- |
| A | SwiftShader | `locator-png` | workspace copy |
| B | Metal | `locator-png` | workspace copy |
| C | Metal | selected `data-url-png` | workspace copy |
| D | Metal | selected `data-url-png` | source-path reuse |

For every row retain the complete performance report, backend attestation,
phase totals, rendered/reused sequence counts, avoided bytes, peak RSS, QA
status, decoded final-media metrics, artifact hashes, concat mode/fallback,
and boundary QA result. Compare each cumulative step against its immediate
predecessor and report percentage change from the measured outer wall time.
Do not add `phase_totals_ms` to estimate a total.

The expected cumulative prediction for D is the A total minus the separately
measured backend, capture, and copy contributions. If D differs from that
prediction by more than 15%, run only the missing backend/capture/reuse
combinations needed to identify the interaction, append them to the benchmark
record, and describe the interaction rather than crediting one isolated
change. Never claim a target speedup that the measured rows did not show.
