import type {Vec3} from '../types.js';


export type HrCategory =
  | 'main_sequence'
  | 'red_giant'
  | 'supergiant'
  | 'white_dwarf';


export interface HrStar {
  id: string;
  name: string;
  spectralType: string;
  absoluteMagnitude: number;
  category?: HrCategory;
}


const CLASS_BASE: Readonly<Record<string, number>> = {
  O: 0,
  B: 10,
  A: 20,
  F: 30,
  G: 40,
  K: 50,
  M: 60,
};


export const spectralCoordinate = (spectralType: string): number => {
  const match = /^([OBAFGKM])(\d)$/.exec(spectralType);
  if (!match) throw new Error(`invalid spectral type: ${spectralType}`);
  return CLASS_BASE[match[1]!]! + Number(match[2]);
};


export const hrChartPosition = (
  star: Pick<HrStar, 'spectralType' | 'absoluteMagnitude'>,
): Vec3 => {
  const spectral = spectralCoordinate(star.spectralType);
  if (star.absoluteMagnitude < -10 || star.absoluteMagnitude > 16) {
    throw new Error(
      `absolute magnitude outside H-R domain: ${star.absoluteMagnitude}`,
    );
  }
  return {
    x: -3.2 + (spectral / 69) * 6.4,
    y: 2.25 - ((star.absoluteMagnitude + 10) / 26) * 4.5,
    z: 0,
  };
};


export const STELLAR_RADII_KM = Object.freeze({
  sun: 700_000,
  arcturus: 20_000_000,
  antares: 470_000_000,
});


export const HR_SOURCE_STARS: readonly HrStar[] = Object.freeze([
  {id: 'deneb', name: '데네브', spectralType: 'A2', absoluteMagnitude: -8.7,
    category: 'supergiant'},
  {id: 'rigel', name: '리겔', spectralType: 'B8', absoluteMagnitude: -6.7,
    category: 'supergiant'},
  {id: 'mintaka', name: '민타카', spectralType: 'O9', absoluteMagnitude: -5.8,
    category: 'main_sequence'},
  {id: 'antares', name: '안타레스', spectralType: 'M1', absoluteMagnitude: -5.6,
    category: 'supergiant'},
  {id: 'canopus', name: '카노푸스', spectralType: 'F0', absoluteMagnitude: -5.5,
    category: 'supergiant'},
  {id: 'betelgeuse', name: '베텔게우스', spectralType: 'M2', absoluteMagnitude: -5.1,
    category: 'supergiant'},
  {id: 'acrux', name: '아크룩스', spectralType: 'B0', absoluteMagnitude: -4.2,
    category: 'main_sequence'},
  {id: 'mimosa', name: '미모사', spectralType: 'B0', absoluteMagnitude: -3.9,
    category: 'main_sequence'},
  {id: 'achernar', name: '아케르나르', spectralType: 'B3', absoluteMagnitude: -2.8,
    category: 'main_sequence'},
  {id: 'spica', name: '스피카', spectralType: 'B1', absoluteMagnitude: -3.6,
    category: 'main_sequence'},
  {id: 'capella', name: '카펠라', spectralType: 'G8', absoluteMagnitude: -0.5,
    category: 'red_giant'},
  {id: 'aldebaran', name: '알데바란', spectralType: 'K5', absoluteMagnitude: -0.6,
    category: 'red_giant'},
  {id: 'arcturus', name: '아르크투루스', spectralType: 'K2', absoluteMagnitude: -0.3,
    category: 'red_giant'},
  {id: 'vega', name: '베가', spectralType: 'A0', absoluteMagnitude: 0.6,
    category: 'main_sequence'},
  {id: 'pollux', name: '폴룩스', spectralType: 'K0', absoluteMagnitude: 1.1,
    category: 'red_giant'},
  {id: 'sirius-a', name: '시리우스 A', spectralType: 'A1', absoluteMagnitude: 1.5,
    category: 'main_sequence'},
  {id: 'fomalhaut', name: '포말하우트', spectralType: 'A3', absoluteMagnitude: 1.7,
    category: 'main_sequence'},
  {id: 'altair', name: '알타이르', spectralType: 'A7', absoluteMagnitude: 2.2,
    category: 'main_sequence'},
  {id: 'procyon-a', name: '프로키온 A', spectralType: 'F5', absoluteMagnitude: 2.7,
    category: 'main_sequence'},
  {id: 'alpha-centauri-a', name: '센타우루스 A', spectralType: 'G2',
    absoluteMagnitude: 4.3, category: 'main_sequence'},
  {id: 'sun', name: '태양', spectralType: 'G2', absoluteMagnitude: 4.8,
    category: 'main_sequence'},
  {id: 'alpha-centauri-b', name: '센타우루스 B', spectralType: 'K1',
    absoluteMagnitude: 5.7, category: 'main_sequence'},
  {id: 'epsilon-eridani', name: '에리다누스자리 ε', spectralType: 'K2',
    absoluteMagnitude: 6.2, category: 'main_sequence'},
  {id: '61-cygni-a', name: '백조자리 A', spectralType: 'K5', absoluteMagnitude: 7.5,
    category: 'main_sequence'},
  {id: '61-cygni-b', name: '백조자리 B', spectralType: 'K7', absoluteMagnitude: 8.3,
    category: 'main_sequence'},
  {id: 'kapteyn', name: '캅테인', spectralType: 'M0', absoluteMagnitude: 10.9,
    category: 'main_sequence'},
  {id: 'sirius-b', name: '시리우스 B', spectralType: 'B1', absoluteMagnitude: 11.3,
    category: 'white_dwarf'},
  {id: 'procyon-b', name: '프로키온 B', spectralType: 'A8', absoluteMagnitude: 13.0,
    category: 'white_dwarf'},
  {id: 'barnards-star', name: '바너드별', spectralType: 'M5', absoluteMagnitude: 13.2,
    category: 'main_sequence'},
  {id: 'alpha-centauri-c', name: '센타우루스 C', spectralType: 'M5',
    absoluteMagnitude: 15.5, category: 'main_sequence'},
]);


export const validateHrStarCatalog = (stars: readonly HrStar[]): void => {
  const ids = new Set<string>();
  for (const star of stars) {
    if (ids.has(star.id)) throw new Error(`duplicate H-R star ID: ${star.id}`);
    ids.add(star.id);
    spectralCoordinate(star.spectralType);
    hrChartPosition(star);
  }
};


validateHrStarCatalog(HR_SOURCE_STARS);


export const hrStarById = (id: string): HrStar => {
  const star = HR_SOURCE_STARS.find((candidate) => candidate.id === id);
  if (!star) throw new Error(`unknown H-R star ID: ${id}`);
  return star;
};
