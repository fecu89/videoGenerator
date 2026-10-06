import type {TemplateName} from './scenes/contracts.js';
import type {RendererBackendInfo, RenderTimingSummary} from './render-telemetry.js';
import type {CaptureMethod, CaptureTimingMode} from './frame-capture.js';


export interface LegacyRenderJob {
  /** Production defaults to SwiftShader; Metal remains an explicit attested opt-in. */
  renderer_backend?: 'metal' | 'swiftshader';
  scene_id: number;
  title: string;
  template: TemplateName;
  simulation_day_start: number;
  simulation_day_end: number;
  duration_seconds: number;
  frame_count: number;
  output_directory: string;
  output: {
    width: number;
    height: number;
    fps: number;
  };
  physics?: {
    earth_period_days: number;
    mars_period_days: number;
    earth_orbit_radius: number;
    mars_orbit_radius: number;
    opposition_day: number;
  };
  style: {
    seed: number;
    earth_scale: number;
    mars_scale?: number;
    moon_scale?: number;
    sun_scale?: number;
  };
  camera?: {
    projection: 'perspective' | 'orthographic';
    framing: string;
    movement: string;
    position?: [number, number, number];
    target?: [number, number, number];
    orientation_convention?: string;
    screen_direction_convention?: string;
  };
  renderer_options?: Record<string, unknown>;
  eclipse?: {
    parameters: Record<string, unknown>;
    renderer_options: Record<string, unknown>;
  };
}


export type PatchTarget =
  | 'simulation_clock'
  | 'geometry'
  | 'layers'
  | 'entities'
  | 'camera'
  | 'hide_events';


export interface SequenceTimelineItem {
  beat_id: string;
  start_frame: number;
  end_frame: number;
  simulation_time_start: number;
  simulation_time_end: number;
  controller: string;
  patch_targets: PatchTarget[];
  priority: number;
  controller_options: Record<string, unknown>;
  hold_intent?: string;
}


export interface SequenceRenderJob {
  job_kind: 'sequence';
  sequence_id: string;
  scene_graph: string;
  /** Per-scene camera paths should honor this duration; no global video retiming. */
  camera_transition_seconds?: number;
  pacing?: {preset: string; version: number; label: string; customized: boolean; target_beat_min_seconds: number; target_beat_max_seconds: number; camera_transition_seconds: number};
  canonical_fps: number;
  duration_frames: number;
  frame_count: number;
  output_directory: string;
  output: {width: number; height: number; fps: number};
  timeline: SequenceTimelineItem[];
  canonical_state_cache: Array<{
    canonical_frame: number;
    active_beat_ids: string[];
    simulation_time: number;
  }>;
  sample_frames: number[];
  physics?: LegacyRenderJob['physics'];
  style: LegacyRenderJob['style'];
  variant_profile?: Record<string, unknown>;
  /** Production defaults to SwiftShader; Metal remains an explicit attested opt-in. */
  renderer_backend?: 'metal' | 'swiftshader';
}


export interface SequenceStateSample {
  continuity?: Record<string, unknown>;
  canonical_frame: number;
  simulation_time: number;
  visible_layers: string[];
  geometry_operation_keys: string[];
  camera: {
    position: [number, number, number];
    target: [number, number, number];
  };
  entity_scales: Record<string, number>;
  state_fingerprint: string;
  callouts?: Array<Record<string, unknown>>;
}


export interface LegacyFrameReport {
  scene_id: number;
  frame_count: number;
  width: number;
  height: number;
  frames: string[];
  browser_version: string;
  capture_method: CaptureMethod;
  capture_timing_mode: CaptureTimingMode;
  capture_transport_bytes: number;
  backend: RendererBackendInfo;
  timings: RenderTimingSummary;
}


export interface SequenceFrameReport {
  sequence_id: string;
  frame_count: number;
  width: number;
  height: number;
  frames: string[];
  browser_version: string;
  capture_method: CaptureMethod;
  capture_timing_mode: CaptureTimingMode;
  capture_transport_bytes: number;
  state_samples: SequenceStateSample[];
  backend: RendererBackendInfo;
  timings: RenderTimingSummary;
}


export type FrameReport = LegacyFrameReport | SequenceFrameReport;
export type RenderJob = LegacyRenderJob | SequenceRenderJob;
