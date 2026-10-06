import * as THREE from 'three';

export const SAFE_MARGIN = 0.04;
export const LABEL_HEIGHT_PX: Record<string, number> = {word: 210, formula: 210, unit: 105};
const CJK_GLYPH_WIDTH = 1.0;   // Hangul/CJK advance a full em
const LATIN_GLYPH_WIDTH = 0.6;
const REFERENCE_FRAME = [1920, 1080] as const;
const GLOW_GAIN = 1.5;
const SCALE_GAIN = 0.25;

export type Side = 'top' | 'bottom' | 'left' | 'right';
export interface CalloutLabel {text: string; anchor: string; side?: Side; emphasis?: 'none' | 'glow' | 'scale'; kind?: 'word' | 'formula' | 'unit'}
export interface CalloutState {text: string; anchor: string; kind: string; rect: [number, number, number, number]; leader: [number, number][]; amount: number}
type Rect = [number, number, number, number];
type XY = [number, number];

function isWide(char: string): boolean {
  const code = char.codePointAt(0) ?? 0;
  return (code >= 0x1100 && code <= 0x11ff) || (code >= 0x2e80 && code <= 0x9fff) || (code >= 0xac00 && code <= 0xd7af)
    || (code >= 0xf900 && code <= 0xfaff) || (code >= 0xff00 && code <= 0xff60);
}

export function textWidthEm(text: string): number {
  let em = 0;
  for (const char of text) em += isWide(char) ? CJK_GLYPH_WIDTH : LATIN_GLYPH_WIDTH;
  return em;
}

export function textBox(text: string, kind: string, _width: number, _height: number): XY {
  const px = LABEL_HEIGHT_PX[kind] ?? 210;
  return [(textWidthEm(text) * px) / REFERENCE_FRAME[0], px / REFERENCE_FRAME[1]];
}

/** Max emphasis per anchor when several labels (across beats) share one object. */
export function anchorAmounts(pairs: Array<[string, number]>): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [name, amount] of pairs) result[name] = Math.max(result[name] ?? 0, amount);
  return result;
}

function clamp(rect: Rect): Rect {
  const w = rect[2] - rect[0], h = rect[3] - rect[1];
  const x0 = Math.min(Math.max(rect[0], SAFE_MARGIN), 1 - SAFE_MARGIN - w);
  const y0 = Math.min(Math.max(rect[1], SAFE_MARGIN), 1 - SAFE_MARGIN - h);
  return [x0, y0, x0 + w, y0 + h];
}

export function labelRect([ax, ay]: XY, [rx, ry]: XY, side: Side, [w, h]: XY, gap = 0.03): Rect {
  switch (side) {
    case 'right': return clamp([ax + rx + gap, ay - h / 2, ax + rx + gap + w, ay + h / 2]);
    case 'left': return clamp([ax - rx - gap - w, ay - h / 2, ax - rx - gap, ay + h / 2]);
    case 'top': return clamp([ax - w / 2, ay - ry - gap - h, ax + w / 2, ay - ry - gap]);
    case 'bottom': return clamp([ax - w / 2, ay + ry + gap, ax + w / 2, ay + ry + gap + h]);
  }
}

export function leaderPoints([ax, ay]: XY, [rx, ry]: XY, rect: Rect, side: Side): [XY, XY, XY] {
  if (side === 'left' || side === 'right') {
    const end: XY = [side === 'right' ? rect[0] : rect[2], (rect[1] + rect[3]) / 2];
    const start: XY = [side === 'right' ? ax + rx : ax - rx, ay];
    return [start, [end[0], start[1]], end];
  }
  const end: XY = [(rect[0] + rect[2]) / 2, side === 'top' ? rect[3] : rect[1]];
  const start: XY = [ax, side === 'top' ? ay - ry : ay + ry];
  return [start, [start[0], end[1]], end];
}

export function fadeAmount(frame: number, start: number, end: number, fps: number, seconds = 0.4): number {
  if (frame < start || frame >= end) return 0;
  const ramp = Math.max(1, Math.round(fps * seconds));
  return Math.max(0, Math.min(1, (frame - start) / ramp, (end - frame) / ramp));
}

interface Item {label: CalloutLabel; kind: string; start: number; end: number; anchor: THREE.Object3D; baseScale: THREE.Vector3; baseEmissive: number[]; amount: number; state?: CalloutState}

function emissiveMaterials(root: THREE.Object3D): THREE.MeshStandardMaterial[] {
  const found: THREE.MeshStandardMaterial[] = [];
  root.traverse((o) => {
    const m = (o as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
    if (m && 'emissiveIntensity' in m) found.push(m);
  });
  return found;
}

export class CalloutLayer {
  private items: Item[] = [];
  private lastAmounts: Record<string, number> = {};
  constructor(private width: number, private height: number) {}

  bind(beats: Array<{labels: CalloutLabel[]; start_frame: number; end_frame: number}>, objects: Record<string, THREE.Object3D>): void {
    for (const beat of beats) for (const label of beat.labels) {
      const anchor = objects[label.anchor];
      if (!anchor) throw new Error(`callout anchor missing: ${label.anchor}`);
      this.items.push({label, kind: label.kind ?? 'word', start: beat.start_frame, end: beat.end_frame, anchor, amount: 0,
        baseScale: anchor.scale.clone(), baseEmissive: emissiveMaterials(anchor).map((m) => m.emissiveIntensity)});
    }
  }

  update(frame: number, fps: number, camera: THREE.Camera): CalloutState[] {
    const aspect = this.width / this.height;
    for (const item of this.items) {
      let amount = fadeAmount(frame, item.start, item.end, fps);
      const world = item.anchor.getWorldPosition(new THREE.Vector3());
      const local = world.clone().applyMatrix4(camera.matrixWorldInverse);
      const p = world.clone().project(camera);
      const ortho = camera instanceof THREE.OrthographicCamera;
      if (!ortho && local.z >= -1e-6) amount = 0;
      const anchorUnit: XY = [(p.x + 1) / 2, (1 - p.y) / 2];
      const sphere = (item.anchor as THREE.Mesh).geometry?.boundingSphere;
      const radius = (sphere?.radius ?? 0.1) * item.anchor.getWorldScale(new THREE.Vector3()).x;
      const halfW = ortho
        ? ((camera as THREE.OrthographicCamera).right - (camera as THREE.OrthographicCamera).left) / 2 / (camera as THREE.OrthographicCamera).zoom
        : -local.z * Math.tan(((camera as THREE.PerspectiveCamera).fov * Math.PI) / 360) * aspect;
      const rUnit: XY = [radius / (2 * halfW), (radius / (2 * halfW)) * aspect];
      const box = textBox(item.label.text, item.kind, this.width, this.height);
      const side = item.label.side ?? 'right';
      const rect = labelRect(anchorUnit, rUnit, side, box);
      const leader = leaderPoints(anchorUnit, rUnit, rect, side);
      item.amount = amount;
      item.state = {text: item.label.text, anchor: item.label.anchor, kind: item.kind, rect, leader, amount};
    }
    // One write per anchor per frame, only while a label is active or just went
    // inactive, so the sequence's own animation of that object is not overridden.
    const amounts = anchorAmounts(this.items.map((i) => [i.label.anchor, i.amount] as [string, number]));
    for (const item of this.items) {
      const name = item.label.anchor, amount = amounts[name] ?? 0;
      if (amount > 0 || (this.lastAmounts[name] ?? 0) > 0) this.emphasise(item, amount);
    }
    this.lastAmounts = amounts;
    return this.screenState();
  }

  private emphasise(item: Item, amount: number): void {
    const mode = item.label.emphasis ?? 'glow';
    if (mode === 'scale') item.anchor.scale.copy(item.baseScale).multiplyScalar(1 + SCALE_GAIN * amount);
    if (mode === 'glow') {
      emissiveMaterials(item.anchor).forEach((m, i) => {m.emissiveIntensity = (item.baseEmissive[i] ?? 1) * (1 + GLOW_GAIN * amount);});
    }
  }

  paint(ctx: CanvasRenderingContext2D): void {
    const W = this.width, H = this.height;
    for (const item of this.items) {
      const s = item.state;
      if (!s || s.amount < 0.002) continue;
      ctx.save();
      ctx.globalAlpha = s.amount;
      ctx.strokeStyle = '#ebf2ff';
      ctx.fillStyle = '#ebf2ff';
      ctx.lineWidth = Math.max(2, (0.018 / 16) * W);
      ctx.beginPath();
      ctx.moveTo(s.leader[0]![0] * W, s.leader[0]![1] * H);
      for (const [x, y] of s.leader.slice(1)) ctx.lineTo(x * W, y * H);
      ctx.stroke();
      const px = (LABEL_HEIGHT_PX[s.kind] ?? 210) * (H / REFERENCE_FRAME[1]);
      ctx.font = `700 ${px}px "Apple SD Gothic Neo", "Noto Sans CJK KR", sans-serif`;
      ctx.textBaseline = 'bottom';
      ctx.fillText(s.text, s.rect[0] * W, s.rect[3] * H);
      ctx.restore();
    }
  }

  screenState(): CalloutState[] {
    return this.items.flatMap((i) => (i.state ? [i.state] : []));
  }
}
