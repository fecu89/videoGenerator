import {describe, expect, it} from 'vitest';
import {textBox, labelRect, leaderPoints, fadeAmount, anchorAmounts, SAFE_MARGIN} from '../src/callout.js';

describe('callout geometry matches the Python reference', () => {
  it('scales 1080p label heights to the frame with per-script glyph widths', () => {
    const [w, h] = textBox('흑운모', 'word', 1920, 1080);
    expect(h).toBeCloseTo(210 / 1080);
    expect(w).toBeCloseTo((1.0 * 210 * 3) / 1920);
    const [w2, h2] = textBox('km', 'unit', 384, 216);
    expect(h2).toBeCloseTo(105 / 1080);
    expect(w2).toBeCloseTo((0.6 * 105 * 2) / 1920);
  });
  it('takes the max emphasis per anchor across labels', () => {
    expect(anchorAmounts([['a', 0], ['a', 0.7], ['b', 0.2], ['a', 0.3]])).toEqual({a: 0.7, b: 0.2});
  });
  it('places the rect outside the anchor and inside the safe area', () => {
    const right = labelRect([0.5, 0.5], [0.05, 0.08], 'right', [0.2, 0.1]);
    expect(right[0]).toBeCloseTo(0.58);
    expect(right[1]).toBeCloseTo(0.45);
    const edge = labelRect([0.98, 0.5], [0.01, 0.01], 'right', [0.2, 0.1]);
    expect(edge[2]).toBeLessThanOrEqual(1 - SAFE_MARGIN);
  });
  it('draws a three-point leader from the anchor edge to the rect edge', () => {
    const rect = labelRect([0.5, 0.5], [0.05, 0.08], 'right', [0.2, 0.1]);
    const [start, elbow, end] = leaderPoints([0.5, 0.5], [0.05, 0.08], rect, 'right');
    expect(start).toEqual([0.55, 0.5]);
    expect(end[0]).toBeCloseTo(rect[0]);
    expect(elbow).toEqual([end[0], 0.5]);
  });
  it('fades in and out over 0.4 s', () => {
    expect(fadeAmount(6, 0, 100, 30)).toBeCloseTo(0.5);
    expect(fadeAmount(12, 0, 100, 30)).toBe(1);
    expect(fadeAmount(100, 0, 100, 30)).toBe(0);
  });
});
