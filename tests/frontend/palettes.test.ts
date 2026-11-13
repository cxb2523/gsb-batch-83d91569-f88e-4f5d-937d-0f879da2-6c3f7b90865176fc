import { describe, expect, test } from "vitest";
import { DEFAULT_PALETTE_ID, getPalette, PALETTES, paletteToCssVars } from "../../apps/frontend/src/theme/palettes";

describe("diorama palettes", () => {
  test("offers twelve unique palettes and resolves unknown settings to Abyss Gold", () => {
    expect(PALETTES).toHaveLength(12);
    expect(new Set(PALETTES.map(p => p.id)).size).toBe(12);
    expect(DEFAULT_PALETTE_ID).toBe("abyss-gold");
    expect(getPalette("unknown").id).toBe(DEFAULT_PALETTE_ID);
  });

  test("every palette supplies the same eight CSS colour roles", () => {
    const keys = ["--c-bg", "--c-panel", "--c-input", "--c-border", "--c-accent", "--c-on-accent", "--c-text", "--c-muted"];
    for (const palette of PALETTES) {
      expect(Object.keys(paletteToCssVars(palette))).toEqual(keys);
      expect(Object.values(paletteToCssVars(palette))).toEqual([
        palette.bg, palette.panel, palette.input, palette.border, palette.accent, palette.onAccent, palette.text, palette.muted
      ]);
    }
  });
});
