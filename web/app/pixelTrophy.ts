// Logo del sitio: un trofeo en pixel-art de 8x8, en vez de una letra "R" en
// caja de color (confundia con el logo de Rockstar Games). Grilla compartida
// entre el mark del header (icons.tsx, SVG con currentColor), la social-card
// (satori/next-og) y el favicon (ver scripts/generate-favicon.py).
export const TROPHY_GRID = 8;

export const TROPHY_PIXELS: Array<[number, number]> = [
  [2, 0], [3, 0], [4, 0], [5, 0],
  [1, 1], [2, 1], [3, 1], [4, 1], [5, 1], [6, 1],
  [1, 2], [2, 2], [3, 2], [4, 2], [5, 2], [6, 2],
  [2, 3], [3, 3], [4, 3], [5, 3],
  [3, 4], [4, 4],
  [3, 5], [4, 5],
  [2, 6], [3, 6], [4, 6], [5, 6],
  [1, 7], [2, 7], [3, 7], [4, 7], [5, 7], [6, 7],
];
