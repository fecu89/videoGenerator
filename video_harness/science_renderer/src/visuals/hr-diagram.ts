import * as THREE from 'three';

import {
  HR_SOURCE_STARS,
  STELLAR_RADII_KM,
  hrChartPosition,
  hrStarById,
  spectralCoordinate,
  type HrCategory,
} from '../data/hr-stars.js';


export type HrRadiusBody = keyof typeof STELLAR_RADII_KM;


export interface HrDiagramSceneObjects {
  group: THREE.Group;
  chartGroup: THREE.Group;
  axes: THREE.Group;
  axisLabels: THREE.Group;
  sourceStars: THREE.Points;
  namedStarMarkers: THREE.Group;
  regions: Record<HrCategory, THREE.Mesh>;
  regionLabels: THREE.Group;
  temperatureGuide: THREE.Line;
  highlightRing: THREE.Mesh;
  radiusGroup: THREE.Group;
  radiusBodies: Record<HrRadiusBody, THREE.Mesh>;
  radiusLabels: Record<HrRadiusBody, THREE.Sprite>;
  scaleIndicator: THREE.Line;
  scaleLabel: THREE.Sprite;
}


const SPECTRAL_COLORS: Readonly<Record<string, number>> = {
  O: 0x7dafff,
  B: 0x9ec5ff,
  A: 0xd5e2ff,
  F: 0xfff4d3,
  G: 0xffdf75,
  K: 0xffac62,
  M: 0xff694c,
};


const labelSprite = (
  text: string,
  color = '#eaf4ff',
  scale: readonly [number, number] = [1.35, 0.34],
): THREE.Sprite => {
  const material = new THREE.SpriteMaterial({
    color: 0xffffff,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  });
  if (typeof document !== 'undefined') {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 128;
    const context = canvas.getContext('2d');
    if (!context) throw new Error(`cannot create H-R label canvas: ${text}`);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.font = '700 48px sans-serif';
    context.fillStyle = color;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, canvas.width / 2, canvas.height / 2, 480);
    material.map = new THREE.CanvasTexture(canvas);
    material.needsUpdate = true;
  }
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(scale[0], scale[1], 1);
  sprite.userData.label = text;
  sprite.userData.textRenderMaxWidth = 480;
  sprite.renderOrder = 20;
  return sprite;
};


const lineSegments = (
  points: readonly THREE.Vector3[],
  color: number,
  opacity = 0.8,
): THREE.LineSegments => new THREE.LineSegments(
  new THREE.BufferGeometry().setFromPoints([...points]),
  new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
  }),
);


const createAxes = (): {axes: THREE.Group; labels: THREE.Group} => {
  const axes = new THREE.Group();
  axes.name = 'hr-axes';
  const borderPoints = [
    new THREE.Vector3(-3.35, -2.4, 0), new THREE.Vector3(3.35, -2.4, 0),
    new THREE.Vector3(3.35, -2.4, 0), new THREE.Vector3(3.35, 2.4, 0),
    new THREE.Vector3(3.35, 2.4, 0), new THREE.Vector3(-3.35, 2.4, 0),
    new THREE.Vector3(-3.35, 2.4, 0), new THREE.Vector3(-3.35, -2.4, 0),
  ];
  axes.add(lineSegments(borderPoints, 0x9fc5dd, 0.82));

  const tickPoints: THREE.Vector3[] = [];
  for (let index = 0; index < 7; index += 1) {
    const x = -3.2 + (index / 6) * 6.4;
    tickPoints.push(
      new THREE.Vector3(x, -2.4, 0),
      new THREE.Vector3(x, -2.3, 0),
    );
  }
  for (const magnitude of [-10, -5, 0, 5, 10, 15]) {
    const y = 2.25 - ((magnitude + 10) / 26) * 4.5;
    tickPoints.push(
      new THREE.Vector3(-3.35, y, 0),
      new THREE.Vector3(-3.25, y, 0),
    );
  }
  axes.add(lineSegments(tickPoints, 0x88abc1, 0.65));

  const labels = new THREE.Group();
  labels.name = 'hr-axis-labels';
  for (const [index, spectralClass] of ['O', 'B', 'A', 'F', 'G', 'K', 'M'].entries()) {
    const label = labelSprite(spectralClass, '#cfe8ff', [0.42, 0.24]);
    label.position.set(-3.2 + (index / 6) * 6.4, -2.63, 0.02);
    labels.add(label);
  }
  for (const magnitude of [-10, -5, 0, 5, 10, 15]) {
    const label = labelSprite(String(magnitude), '#cfe8ff', [0.6, 0.24]);
    label.position.set(
      -3.67,
      2.25 - ((magnitude + 10) / 26) * 4.5,
      0.02,
    );
    labels.add(label);
  }
  const horizontal = labelSprite(
    '고온 ← 분광형 → 저온',
    '#f4f8ff',
    [3.25, 0.42],
  );
  horizontal.position.set(0, -2.93, 0.02);
  labels.add(horizontal);
  const vertical = labelSprite('절대 등급  밝음 ↑', '#f4f8ff', [1.7, 0.38]);
  vertical.position.set(-3.7, 2.68, 0.02);
  labels.add(vertical);
  return {axes, labels};
};


const createSourceStars = (): THREE.Points => {
  const positions: number[] = [];
  const colors: number[] = [];
  for (const star of HR_SOURCE_STARS) {
    const position = hrChartPosition(star);
    positions.push(position.x, position.y, 0.08);
    const color = new THREE.Color(SPECTRAL_COLORS[star.spectralType[0]!]!);
    colors.push(color.r, color.g, color.b);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.setDrawRange(0, 0);
  const points = new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      size: 0.105,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.98,
      vertexColors: true,
      depthWrite: false,
    }),
  );
  points.name = 'hr-source-stars';
  points.userData.sourceStarIds = Object.freeze(HR_SOURCE_STARS.map((star) => star.id));
  return points;
};


const regionMesh = (
  name: HrCategory,
  color: number,
  width: number,
  height: number,
  x: number,
  y: number,
  rotation = 0,
): THREE.Mesh => {
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.19,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  mesh.name = `hr-region-${name}`;
  mesh.position.set(x, y, -0.04);
  mesh.rotation.z = rotation;
  mesh.visible = false;
  return mesh;
};


const createRegions = (): Record<HrCategory, THREE.Mesh> => ({
  main_sequence: regionMesh(
    'main_sequence', 0x4683d8, 6.1, 0.54, 0, -0.05, -0.49,
  ),
  red_giant: regionMesh('red_giant', 0xf49a59, 2.0, 0.82, 2.05, 0.83, -0.08),
  supergiant: regionMesh('supergiant', 0xffd170, 5.9, 0.5, 0.25, 1.82),
  white_dwarf: regionMesh('white_dwarf', 0x8bdcf2, 1.8, 0.68, -1.8, -1.46, -0.18),
});


const createRegionLabels = (): THREE.Group => {
  const labels = new THREE.Group();
  labels.name = 'hr-region-labels';
  const entries: readonly [HrCategory, string, number, number][] = [
    ['main_sequence', '주계열성', 0.1, 0.15],
    ['red_giant', '적색 거성', 2.05, 1.28],
    ['supergiant', '초거성', 0.25, 2.12],
    ['white_dwarf', '백색 왜성', -1.85, -1.05],
  ];
  for (const [category, text, x, y] of entries) {
    const label = labelSprite(text, '#ffffff', [1.15, 0.3]);
    label.name = `hr-region-label-${category}`;
    label.position.set(x, y, 0.12);
    label.visible = false;
    labels.add(label);
  }
  return labels;
};


const createNamedStarMarkers = (): THREE.Group => {
  const markers = new THREE.Group();
  markers.name = 'hr-named-star-markers';
  for (const id of ['antares', 'sun', 'sirius-b', 'arcturus'] as const) {
    const star = hrStarById(id);
    const position = hrChartPosition(star);
    const marker = new THREE.Mesh(
      new THREE.RingGeometry(0.12, 0.165, 40),
      new THREE.MeshBasicMaterial({
        color: 0xffef9f,
        transparent: true,
        opacity: 0.96,
        side: THREE.DoubleSide,
        depthTest: false,
        depthWrite: false,
      }),
    );
    marker.name = `hr-marker-${id}`;
    marker.position.set(position.x, position.y, 0.11);
    marker.userData.starId = id;
    marker.visible = false;
    const label = labelSprite(star.name, '#fff5bd', [1.08, 0.28]);
    label.name = `hr-marker-label-${id}`;
    label.position.set(position.x + 0.45, position.y + 0.2, 0.13);
    label.userData.starId = id;
    label.visible = false;
    markers.add(marker, label);
  }
  return markers;
};


const radiusBody = (
  id: HrRadiusBody,
  color: number,
): THREE.Mesh => {
  const body = new THREE.Mesh(
    new THREE.SphereGeometry(1, 48, 32),
    new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.18,
      roughness: 0.92,
    }),
  );
  body.name = `hr-radius-${id}`;
  body.userData.radiusKm = STELLAR_RADII_KM[id];
  body.visible = false;
  return body;
};


const setPairScale = (
  objects: Pick<HrDiagramSceneObjects, 'radiusBodies' | 'radiusLabels'>,
  left: HrRadiusBody,
  right: HrRadiusBody,
): void => {
  const {radiusBodies: bodies, radiusLabels: labels} = objects;
  for (const body of Object.values(bodies)) body.visible = false;
  for (const label of Object.values(labels)) label.visible = false;
  const maxRadius = Math.max(STELLAR_RADII_KM[left], STELLAR_RADII_KM[right]);
  const displayRadius = 0.92;
  bodies[left].visible = true;
  bodies[right].visible = true;
  bodies[left].scale.setScalar(displayRadius * STELLAR_RADII_KM[left] / maxRadius);
  bodies[right].scale.setScalar(displayRadius * STELLAR_RADII_KM[right] / maxRadius);
  bodies[left].position.set(-1.45, 0, 0);
  bodies[right].position.set(1.45, 0, 0);
  labels[left].visible = true;
  labels[right].visible = true;
  labels[left].position.set(-1.45, 1.32, 0.1);
  labels[right].position.set(1.45, 1.32, 0.1);
};


export const createHrDiagramSystem = (): HrDiagramSceneObjects => {
  const group = new THREE.Group();
  group.name = 'hr-diagram-system';
  group.visible = false;

  const chartGroup = new THREE.Group();
  chartGroup.name = 'hr-chart';
  chartGroup.scale.set(0.76, 0.62, 1);
  chartGroup.userData.viewportScale = {x: 0.76, y: 0.62};
  const {axes, labels: axisLabels} = createAxes();
  const sourceStars = createSourceStars();
  const namedStarMarkers = createNamedStarMarkers();
  const regions = createRegions();
  const regionLabels = createRegionLabels();

  const arcturus = hrChartPosition(hrStarById('arcturus'));
  const epsilonEridani = hrChartPosition(hrStarById('epsilon-eridani'));
  const temperatureGuide = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(arcturus.x, arcturus.y, 0.04),
      new THREE.Vector3(epsilonEridani.x, epsilonEridani.y, 0.04),
    ]),
    new THREE.LineDashedMaterial({
      color: 0xffd166,
      dashSize: 0.12,
      gapSize: 0.08,
      transparent: true,
      opacity: 0.92,
      depthWrite: false,
    }),
  );
  temperatureGuide.name = 'hr-same-temperature-guide';
  temperatureGuide.computeLineDistances();
  temperatureGuide.visible = false;

  const highlightRing = new THREE.Mesh(
    new THREE.RingGeometry(0.18, 0.23, 48),
    new THREE.MeshBasicMaterial({
      color: 0xffd166,
      transparent: true,
      opacity: 0.98,
      side: THREE.DoubleSide,
      depthTest: false,
      depthWrite: false,
    }),
  );
  highlightRing.name = 'hr-highlight-ring';
  highlightRing.visible = false;

  chartGroup.add(
    ...Object.values(regions),
    axes,
    axisLabels,
    sourceStars,
    regionLabels,
    namedStarMarkers,
    temperatureGuide,
    highlightRing,
  );

  const radiusGroup = new THREE.Group();
  radiusGroup.name = 'hr-radius-comparison';
  radiusGroup.visible = false;
  const radiusBodies = {
    sun: radiusBody('sun', 0xffd45e),
    arcturus: radiusBody('arcturus', 0xff9d4f),
    antares: radiusBody('antares', 0xe55843),
  } satisfies Record<HrRadiusBody, THREE.Mesh>;
  const radiusLabels = {
    sun: labelSprite('태양 · 70만 km', '#ffe49a', [2.45, 0.38]),
    arcturus: labelSprite(
      '아르크투루스 · 2천만 km',
      '#ffc27b',
      [2.5, 0.38],
    ),
    antares: labelSprite(
      '안타레스 · 4억 7천만 km',
      '#ff9b80',
      [2.5, 0.38],
    ),
  } satisfies Record<HrRadiusBody, THREE.Sprite>;
  for (const [id, label] of Object.entries(radiusLabels)) {
    label.name = `hr-radius-label-${id}`;
    label.visible = false;
  }
  const scaleIndicator = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-2.35, -1.75, 0),
      new THREE.Vector3(2.35, -1.75, 0),
    ]),
    new THREE.LineBasicMaterial({
      color: 0xe8f2ff,
      transparent: true,
      opacity: 0.78,
    }),
  );
  scaleIndicator.name = 'hr-radius-scale-indicator';
  scaleIndicator.visible = false;
  const scaleLabel = labelSprite(
    '장면 안 반지름 비율 유지',
    '#dcecff',
    [2.7, 0.34],
  );
  scaleLabel.name = 'hr-radius-scale-label';
  scaleLabel.position.set(0, -2.02, 0.05);
  scaleLabel.visible = false;
  radiusGroup.add(
    ...Object.values(radiusBodies),
    ...Object.values(radiusLabels),
    scaleIndicator,
    scaleLabel,
  );
  group.add(chartGroup, radiusGroup);

  return {
    group,
    chartGroup,
    axes,
    axisLabels,
    sourceStars,
    namedStarMarkers,
    regions,
    regionLabels,
    temperatureGuide,
    highlightRing,
    radiusGroup,
    radiusBodies,
    radiusLabels,
    scaleIndicator,
    scaleLabel,
  };
};


export const resetHrDiagram = (objects: HrDiagramSceneObjects): void => {
  objects.chartGroup.visible = true;
  objects.radiusGroup.visible = false;
  objects.axes.visible = false;
  objects.axisLabels.visible = false;
  objects.sourceStars.geometry.setDrawRange(0, 0);
  setHrRegionReveal(objects, []);
  setHrNamedMarkerReveal(objects, []);
  objects.temperatureGuide.visible = false;
  objects.highlightRing.visible = false;
  objects.scaleIndicator.visible = false;
  objects.scaleLabel.visible = false;
  for (const body of Object.values(objects.radiusBodies)) {
    body.visible = false;
    body.position.set(0, 0, 0);
    body.scale.set(1, 1, 1);
  }
  for (const label of Object.values(objects.radiusLabels)) label.visible = false;
};


export const setHrAxesReveal = (
  objects: HrDiagramSceneObjects,
  progress: number,
): void => {
  const visible = THREE.MathUtils.clamp(progress, 0, 1) > 0;
  objects.axes.visible = visible;
  objects.axisLabels.visible = visible;
};


export const setHrStarReveal = (
  objects: HrDiagramSceneObjects,
  count: number,
): void => {
  objects.sourceStars.geometry.setDrawRange(
    0,
    Math.floor(THREE.MathUtils.clamp(count, 0, HR_SOURCE_STARS.length)),
  );
};


export const setHrRegionReveal = (
  objects: HrDiagramSceneObjects,
  categories: readonly HrCategory[],
): void => {
  const visible = new Set(categories);
  for (const [category, region] of Object.entries(objects.regions) as [
    HrCategory,
    THREE.Mesh,
  ][]) {
    region.visible = visible.has(category);
  }
  for (const child of objects.regionLabels.children) {
    const category = child.name.replace('hr-region-label-', '') as HrCategory;
    child.visible = visible.has(category);
  }
};


export const setHrNamedMarkerReveal = (
  objects: HrDiagramSceneObjects,
  starIds: readonly string[],
): void => {
  const visible = new Set(starIds);
  for (const child of objects.namedStarMarkers.children) {
    child.visible = visible.has(String(child.userData.starId));
  }
};


export const setHrTemperatureGuide = (
  objects: HrDiagramSceneObjects,
  visible: boolean,
): void => {
  objects.temperatureGuide.visible = visible;
};


export const setHrRadiusStage = (
  objects: HrDiagramSceneObjects,
  progress: number,
): void => {
  const clamped = THREE.MathUtils.clamp(progress, 0, 1);
  objects.chartGroup.visible = false;
  objects.radiusGroup.visible = true;
  objects.scaleIndicator.visible = true;
  objects.scaleLabel.visible = true;
  if (clamped < 0.5) {
    setPairScale(objects, 'sun', 'arcturus');
    objects.scaleIndicator.userData.comparison = 'sun-to-arcturus';
  } else {
    setPairScale(objects, 'arcturus', 'antares');
    objects.scaleIndicator.userData.comparison = 'arcturus-to-antares';
  }
};


export const spectralClassChartX = (spectralClass: string): number => (
  -3.2 + (spectralCoordinate(`${spectralClass}0`) / 69) * 6.4
);
