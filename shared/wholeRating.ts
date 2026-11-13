// A rating's whole-number bucket for the Year in Review spread (0..10, half up). Other cards use the exact score.
export const wholeRating = (score: number) => Math.min(10, Math.max(0, Math.floor(score + 0.5)));
