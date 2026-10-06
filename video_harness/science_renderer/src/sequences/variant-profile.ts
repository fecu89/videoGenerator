import type {SequencePatch} from './contracts.js';


export type CameraVariantProfile = 'base' | 'wide' | 'close' | 'restrained';
export type LayerTimingVariantProfile = 'base' | 'explain' | 'dynamic';
export type LightingVariantProfile = 'base' | 'clear' | 'cinematic';
export type ScaleVariantProfile = 'base' | 'emphasis';


export interface SequenceVariantProfile {
  camera_profile: CameraVariantProfile;
  layer_timing_profile: LayerTimingVariantProfile;
  lighting_profile: LightingVariantProfile;
  scale_profile: ScaleVariantProfile;
}


const CAMERA_VALUES = new Set<CameraVariantProfile>([
  'base', 'wide', 'close', 'restrained',
]);
const LAYER_VALUES = new Set<LayerTimingVariantProfile>([
  'base', 'explain', 'dynamic',
]);
const LIGHTING_VALUES = new Set<LightingVariantProfile>([
  'base', 'clear', 'cinematic',
]);
const SCALE_VALUES = new Set<ScaleVariantProfile>(['base', 'emphasis']);
const PROFILE_FIELDS = new Set([
  'camera_profile',
  'layer_timing_profile',
  'lighting_profile',
  'scale_profile',
]);


const requireProfileValue = <T extends string>(
  value: unknown,
  allowed: ReadonlySet<T>,
  field: string,
  fallback: T,
): T => {
  const candidate = value ?? fallback;
  if (typeof candidate !== 'string' || !allowed.has(candidate as T)) {
    throw new Error(`invalid ${field}: ${String(candidate)}`);
  }
  return candidate as T;
};


export const parseSequenceVariantProfile = (
  value: object = {},
): SequenceVariantProfile => {
  const input = value as Readonly<Record<string, unknown>>;
  for (const field of Object.keys(input)) {
    if (!PROFILE_FIELDS.has(field)) {
      throw new Error(`unknown variant profile field: ${field}`);
    }
  }
  return {
    camera_profile: requireProfileValue(
      input.camera_profile, CAMERA_VALUES, 'camera_profile', 'base',
    ),
    layer_timing_profile: requireProfileValue(
      input.layer_timing_profile, LAYER_VALUES, 'layer_timing_profile', 'base',
    ),
    lighting_profile: requireProfileValue(
      input.lighting_profile, LIGHTING_VALUES, 'lighting_profile', 'base',
    ),
    scale_profile: requireProfileValue(
      input.scale_profile, SCALE_VALUES, 'scale_profile', 'base',
    ),
  };
};


const clampProgress = (progress: number): number =>
  Math.min(1, Math.max(0, progress));


export const layerRevealProgress = (
  progress: number,
  profile: Partial<SequenceVariantProfile>,
): number => {
  const normalized = clampProgress(progress);
  switch (profile.layer_timing_profile ?? 'base') {
    case 'explain':
      return Math.min(1, normalized * 1.15);
    case 'dynamic':
      return normalized * normalized * (3 - 2 * normalized);
    case 'base':
      return normalized;
  }
};


export const lightingExposure = (
  profile: Partial<SequenceVariantProfile>,
): number => {
  switch (profile.lighting_profile ?? 'base') {
    case 'clear': return 1.18;
    case 'cinematic': return 0.96;
    case 'base': return 1.1;
  }
};


const cameraDistanceMultiplier = (
  profile: CameraVariantProfile,
): number => {
  switch (profile) {
    case 'wide': return 1.15;
    case 'close': return 0.85;
    case 'restrained': return 1.05;
    case 'base': return 1;
  }
};


export const applySequenceVariantProfile = (
  patch: SequencePatch,
  profile: SequenceVariantProfile,
): SequencePatch => {
  const result = structuredClone(patch);
  const position = result.camera?.position;
  const target = result.camera?.target ?? [0, 0, 0];
  if (position) {
    const multiplier = cameraDistanceMultiplier(profile.camera_profile);
    result.camera!.position = [
      target[0] + (position[0] - target[0]) * multiplier,
      target[1] + (position[1] - target[1]) * multiplier,
      target[2] + (position[2] - target[2]) * multiplier,
    ];
  }
  if (profile.scale_profile === 'emphasis') {
    for (const override of Object.values(result.entityOverrides ?? {})) {
      if (override.scale !== undefined) override.scale *= 1.12;
    }
  }
  return result;
};
