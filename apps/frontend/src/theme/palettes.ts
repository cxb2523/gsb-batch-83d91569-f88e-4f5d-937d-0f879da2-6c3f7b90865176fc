export interface Palette {
  id: string;
  name: string;
  group: "standard" | "darker";
  bg: string; panel: string; input: string; border: string;
  accent: string; onAccent: string; text: string; muted: string;
}

export const PALETTES: readonly Palette[] = [
  { id: "crimson-keep",    name: "Crimson Keep",    group: "standard", bg: "#140A0D", panel: "#24121A", input: "#321A24", border: "#8A5A3C", accent: "#C8894A", onAccent: "#1C0E06", text: "#F2E4D8", muted: "#A68E8E" },
  { id: "verdant-grove",   name: "Verdant Grove",   group: "standard", bg: "#0B1410", panel: "#13221B", input: "#1C3027", border: "#6F7F4E", accent: "#C9C27A", onAccent: "#141505", text: "#E6EDDF", muted: "#8FA398" },
  { id: "amethyst-dusk",   name: "Amethyst Dusk",   group: "standard", bg: "#120C1C", panel: "#1F1530", input: "#2B1E42", border: "#8A6A86", accent: "#E0A98C", onAccent: "#1E0F0A", text: "#EFE3F0", muted: "#A394B3" },
  { id: "obsidian-ember",  name: "Obsidian Ember",  group: "standard", bg: "#0E0D0C", panel: "#1A1816", input: "#252220", border: "#7A5A3A", accent: "#E07A3A", onAccent: "#1A0B03", text: "#F0E8E0", muted: "#9A928A" },
  { id: "umber-parchment", name: "Umber Parchment", group: "standard", bg: "#15100A", panel: "#241B12", input: "#31251A", border: "#9A7B4F", accent: "#E3C07A", onAccent: "#1E1506", text: "#F3E8D2", muted: "#A8977E" },
  { id: "ashen-bronze",    name: "Ashen Bronze",    group: "standard", bg: "#121110", panel: "#1E1C1A", input: "#2A2724", border: "#86735A", accent: "#C9A26B", onAccent: "#1A1206", text: "#ECE7DF", muted: "#9C958B" },
  { id: "rose-noir",       name: "Rose Noir",       group: "standard", bg: "#130B0E", panel: "#22141A", input: "#2F1C24", border: "#8C5C66", accent: "#E39AA6", onAccent: "#200A10", text: "#F5E6EA", muted: "#A88E96" },
  { id: "moss-copper",     name: "Moss and Copper", group: "standard", bg: "#0F110A", panel: "#1B1F13", input: "#262B1B", border: "#8A6A45", accent: "#D08A52", onAccent: "#1C0E04", text: "#ECEBDD", muted: "#9A9C86" },
  { id: "abyss-gold",      name: "Abyss Gold",      group: "darker",   bg: "#060606", panel: "#0E0E0D", input: "#161614", border: "#6E5E3C", accent: "#CFA75A", onAccent: "#140E03", text: "#E9E3D6", muted: "#8A8578" },
  { id: "blood-void",      name: "Blood Void",      group: "darker",   bg: "#070304", panel: "#110709", input: "#1A0C0F", border: "#6A2A2C", accent: "#C0443C", onAccent: "#FFF0EC", text: "#EEDFDC", muted: "#8E7472" },
  { id: "nightshade",      name: "Nightshade",      group: "darker",   bg: "#07050A", panel: "#100C16", input: "#181220", border: "#5E4870", accent: "#C48ADB", onAccent: "#15081C", text: "#ECE4F2", muted: "#8C8196" },
  { id: "black-pine",      name: "Black Pine",      group: "darker",   bg: "#040806", panel: "#0A110D", input: "#111A15", border: "#4E5E3E", accent: "#B8A45C", onAccent: "#121004", text: "#E2E8DE", muted: "#7F8E84" }
];

export const DEFAULT_PALETTE_ID = "abyss-gold";

export function getPalette(id: string | null | undefined): Palette {
  return PALETTES.find(p => p.id === id) ?? PALETTES.find(p => p.id === DEFAULT_PALETTE_ID)!;
}

export function paletteToCssVars(p: Palette): Record<`--${string}`, string> {
  return {
    "--c-bg": p.bg, "--c-panel": p.panel, "--c-input": p.input, "--c-border": p.border,
    "--c-accent": p.accent, "--c-on-accent": p.onAccent, "--c-text": p.text, "--c-muted": p.muted
  };
}
