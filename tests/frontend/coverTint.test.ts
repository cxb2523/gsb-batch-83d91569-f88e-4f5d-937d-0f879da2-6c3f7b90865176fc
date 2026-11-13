import { describe, expect, test } from "vitest";
import { coverTint } from "../../apps/frontend/src/theme/coverTint";

// RGBA pixels: `count` copies of each colour.
function pixels(...runs: Array<[number, number, number, number]>) {
  const data: number[] = [];
  for (const [r, g, b, count] of runs) for (let i = 0; i < count; i++) data.push(r, g, b, 255);
  return new Uint8ClampedArray(data);
}

const channels = (tint: string | null) => tint!.split(" ").map(Number);

describe("cover tint", () => {
  test("follows the cover's colour, not its greys, blacks and whites", () => {
    const [r, g, b] = channels(coverTint(pixels([128, 128, 128, 300], [10, 10, 10, 300], [250, 250, 250, 100], [170, 40, 50, 60])));
    expect(r).toBeGreaterThan(g * 1.8);
    expect(r).toBeGreaterThan(b * 1.8);
  });

  test("the most colourful area wins over a larger dull one", () => {
    const [r, , b] = channels(coverTint(pixels([120, 100, 95, 200], [30, 80, 220, 80])));
    expect(b).toBeGreaterThan(r * 1.5);
  });

  test("a near-black or grey cover gives no tint, so the palette stays as it is", () => {
    expect(coverTint(pixels([128, 128, 128, 200], [5, 5, 5, 200]))).toBeNull();
    expect(coverTint(new Uint8ClampedArray())).toBeNull();
  });

  test("a very dark or very pale colour is brought to a blendable brightness", () => {
    for (const run of [[40, 5, 8, 100], [255, 215, 220, 100]] as Array<[number, number, number, number]>) {
      const [r, g, b] = channels(coverTint(pixels(run)));
      const lightness = (Math.max(r, g, b) + Math.min(r, g, b)) / 2 / 255;
      expect(lightness).toBeGreaterThan(0.35);
      expect(lightness).toBeLessThan(0.65);
      expect(r).toBeGreaterThan(g);
    }
  });
});
