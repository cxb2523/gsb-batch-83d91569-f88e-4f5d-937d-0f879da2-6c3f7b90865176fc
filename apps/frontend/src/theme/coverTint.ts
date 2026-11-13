// The colour a detail page blends toward: the cover's main hue, from its colourful pixels only.
// Greys, blacks and whites are skipped, so dark box art with one red logo still reads as red.
// Returns "r g b" (for rgb(var(--x))) at a fixed, blendable brightness, or null for colourless covers.
export function coverTint(rgba: Uint8ClampedArray): string | null {
  let x = 0;
  let y = 0;
  let saturation = 0;
  let weight = 0;
  const count = Math.floor(rgba.length / 4);
  for (let i = 0; i < count * 4; i += 4) {
    const [h, s, l] = toHsl(rgba[i], rgba[i + 1], rgba[i + 2]);
    if (rgba[i + 3] < 128 || s < 0.15 || l < 0.06 || l > 0.95) continue;
    // Vivid mid-tones count most; nearly-black or nearly-white colour counts a little.
    const w = s * (1 - Math.abs(2 * l - 1));
    x += Math.cos(h) * w;
    y += Math.sin(h) * w;
    saturation += s * w;
    weight += w;
  }
  if (!count || weight / count < 0.02) return null;
  const hue = Math.atan2(y, x);
  const [r, g, b] = fromHsl(hue, Math.min(0.75, Math.max(0.35, saturation / weight)), 0.5);
  return `${r} ${g} ${b}`;
}

// Hue in radians.
function toHsl(red: number, green: number, blue: number): [number, number, number] {
  const r = red / 255, g = green / 255, b = blue / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  const sector = max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(sector / 6) * 2 * Math.PI, s, l];
}

function fromHsl(hue: number, s: number, l: number): [number, number, number] {
  const degrees = ((hue * 180) / Math.PI + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((degrees / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] = degrees < 60 ? [c, x, 0] : degrees < 120 ? [x, c, 0] : degrees < 180 ? [0, c, x] : degrees < 240 ? [0, x, c] : degrees < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map(value => Math.round((value + m) * 255)) as [number, number, number];
}
