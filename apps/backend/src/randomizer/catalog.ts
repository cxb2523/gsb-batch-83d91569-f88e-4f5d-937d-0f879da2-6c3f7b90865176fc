import type { RandomizerOption, RandomizerPlatformOption, RandomizerPreset } from "../../../../shared/types";

// Fixed IGDB ids, checked against the live API on 2026-09-25. Kept static so the
// filter panel needs no IGDB request for them and odd platforms never appear.

// Mainstream PlayStation, Xbox and Nintendo hardware plus PC. Spins are always limited to these.
export const MAINSTREAM_PLATFORMS: RandomizerPlatformOption[] = [
  { id: 6, name: "PC", family: "PC" },
  { id: 7, name: "PlayStation", family: "PlayStation" },
  { id: 8, name: "PlayStation 2", family: "PlayStation" },
  { id: 9, name: "PlayStation 3", family: "PlayStation" },
  { id: 48, name: "PlayStation 4", family: "PlayStation" },
  { id: 167, name: "PlayStation 5", family: "PlayStation" },
  { id: 38, name: "PSP", family: "PlayStation" },
  { id: 46, name: "PS Vita", family: "PlayStation" },
  { id: 11, name: "Xbox", family: "Xbox" },
  { id: 12, name: "Xbox 360", family: "Xbox" },
  { id: 49, name: "Xbox One", family: "Xbox" },
  { id: 169, name: "Xbox Series X|S", family: "Xbox" },
  { id: 18, name: "NES", family: "Nintendo" },
  { id: 19, name: "SNES", family: "Nintendo" },
  { id: 4, name: "Nintendo 64", family: "Nintendo" },
  { id: 21, name: "GameCube", family: "Nintendo" },
  { id: 5, name: "Wii", family: "Nintendo" },
  { id: 41, name: "Wii U", family: "Nintendo" },
  { id: 130, name: "Switch", family: "Nintendo" },
  { id: 508, name: "Switch 2", family: "Nintendo" },
  { id: 33, name: "Game Boy", family: "Nintendo" },
  { id: 22, name: "Game Boy Color", family: "Nintendo" },
  { id: 24, name: "Game Boy Advance", family: "Nintendo" },
  { id: 20, name: "Nintendo DS", family: "Nintendo" },
  { id: 37, name: "Nintendo 3DS", family: "Nintendo" }
];

export const MAINSTREAM_PLATFORM_IDS = MAINSTREAM_PLATFORMS.map(platform => platform.id);

// Popular IGDB keywords with enough rated games to be worth a filter. Open world, stealth,
// sandbox and survival are IGDB themes, so they live in the Themes filter instead.
export const POPULAR_TAGS: RandomizerOption[] = [
  { id: 2231, name: "3D platformer" },
  { id: 1905, name: "Base building" },
  { id: 911, name: "Bullet hell" },
  { id: 3534, name: "Choices matter" },
  { id: 26248, name: "Collectathon" },
  { id: 24685, name: "Cozy" },
  { id: 510, name: "Crafting" },
  { id: 103, name: "Cyberpunk" },
  { id: 537, name: "Dark fantasy" },
  { id: 215, name: "Detective" },
  { id: 2228, name: "Dungeon crawler" },
  { id: 72, name: "Exploration" },
  { id: 1103, name: "Farming" },
  { id: 962, name: "Female protagonist" },
  { id: 1448, name: "Mecha" },
  { id: 477, name: "Metroidvania" },
  { id: 1313, name: "Multiple endings" },
  { id: 164, name: "Ninja" },
  { id: 2377, name: "Party-based" },
  { id: 578, name: "Permadeath" },
  { id: 1705, name: "Pixel art" },
  { id: 69, name: "Post-apocalyptic" },
  { id: 131, name: "Psychological horror" },
  { id: 4527, name: "Puzzle platformer" },
  { id: 416, name: "Roguelike" },
  { id: 17292, name: "Roguelite" },
  { id: 253, name: "Samurai" },
  { id: 17326, name: "Soulslike" },
  { id: 2426, name: "Story rich" },
  { id: 1836, name: "Survival horror" },
  { id: 170, name: "Time travel" },
  { id: 415, name: "Turn-based" },
  { id: 5, name: "Zombies" }
];

// Each preset matches any of its keywords; several presets must all match.
export const PRESET_KEYWORDS: Record<RandomizerPreset, number[]> = {
  jrpg: [521, 19521], // "jrpg", "japanese rpg"
  anime: [78, 345] // "anime", "manga"
};

export const PRESET_LABELS: Record<RandomizerPreset, string> = { jrpg: "JRPG", anime: "anime" };

// ISO 3166-1 numeric code IGDB uses for companies based in Japan.
export const JAPAN_COUNTRY_CODE = 392;
