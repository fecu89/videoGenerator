import {describe, expect, it} from 'vitest';

import {DEFAULT_PHYSICS} from '../src/math/circular-orbit.js';
import {applyGeometryOperations} from '../src/sequences/contracts.js';
import {createSharedScene} from '../src/visuals/solar-system.js';


describe('H-R diagram operation', () => {
  it('reveals points without changing their source coordinates', () => {
    const objects = createSharedScene({seed: 4, width: 320, height: 180});
    const position = objects.hr.sourceStars.geometry.attributes.position!;
    const before = Array.from(position.array);

    applyGeometryOperations(objects, DEFAULT_PHYSICS, [{
      kind: 'hr_diagram',
      key: 'hr-plot',
      template: 'plot-hr-source-stars',
      progress: 0.5,
      parameters: {},
    }]);

    expect(Array.from(position.array)).toEqual(before);
    expect(objects.hr.sourceStars.geometry.drawRange.count).toBe(15);
  });
});
