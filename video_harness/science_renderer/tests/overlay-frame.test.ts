import {describe, expect, it} from 'vitest';

import {
  interpolateOverlayState,
  type OverlayContract,
} from '../src/overlay-frame.js';


const lineContract: OverlayContract = {
  overlay_id: 'sightline',
  type: 'line',
  relationship_id: 'earth_mars_sightline',
  style: {stroke: '#ffffff', width: 2},
  keyframes: [
    {at_seconds: 0, points: [[0.2, 0.5], [0.7, 0.5]]},
    {at_seconds: 1, points: [[0.3, 0.5], [0.8, 0.5]]},
  ],
};


describe('deterministic overlay interpolation', () => {
  it('interpolates an attached line from declared image anchors', () => {
    const state = interpolateOverlayState([lineContract], 0.5);
    expect(state.lines[0]!.from).toEqual([0.25, 0.5]);
    expect(state.lines[0]!.to).toEqual([0.75, 0.5]);
  });

  it('keeps screen anchors fixed across the clip', () => {
    const anchor: OverlayContract = {
      overlay_id: 'anchor',
      type: 'screen_anchor',
      relationship_id: 'fixed_anchor',
      style: {stroke: '#ff0000', radius: 0.01},
      keyframes: [{at_seconds: 0, points: [[0.4, 0.6]]}],
    };
    expect(interpolateOverlayState([anchor], 0.1).anchors[0]).toEqual(
      interpolateOverlayState([anchor], 0.9).anchors[0],
    );
  });

  it('rejects mismatched keyframe point counts', () => {
    const invalid: OverlayContract = {
      ...lineContract,
      keyframes: [
        lineContract.keyframes[0]!,
        {at_seconds: 1, points: [[0.8, 0.5]]},
      ],
    };
    expect(() => interpolateOverlayState([invalid], 0.5)).toThrow(
      'point count',
    );
  });
});
