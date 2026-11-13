// Agrupa las ~50 consolas del dataset por fabricante para la fila de pills
// de /. Lo que no matchea cae en "Otros" -- una consola nueva que se
// agregue al dataset sigue apareciendo ahi sin romper nada, aunque falte
// agregarla aca.
export const COMPANY_ORDER = ["Nintendo", "Sega", "Sony", "Atari", "SNK", "NEC", "Otros"] as const;

export type Company = (typeof COMPANY_ORDER)[number];

const COMPANY_BY_CONSOLE: Record<string, Company> = {
  "NES": "Nintendo",
  "SNES": "Nintendo",
  "N64": "Nintendo",
  "Game Boy": "Nintendo",
  "Game Boy Color": "Nintendo",
  "Game Boy Advance": "Nintendo",
  "Nintendo DS": "Nintendo",
  "Nintendo Dsi": "Nintendo",
  "Virtual Boy": "Nintendo",
  "Pokemon Mini": "Nintendo",
  "WiiWare": "Nintendo",
  "Wii": "Nintendo",
  "GameCube": "Nintendo",

  "Genesis/Mega Drive": "Sega",
  "Master System": "Sega",
  "Game Gear": "Sega",
  "Sega CD": "Sega",
  "Sega 32X": "Sega",
  "Dreamcast": "Sega",
  "SG-1000": "Sega",
  "Saturn": "Sega",

  "PS1": "Sony",
  "PS2": "Sony",
  "PSP": "Sony",

  "Atari 2600": "Atari",
  "Atari 7800": "Atari",
  "Atari Jaguar": "Atari",
  "Atari Jaguar Cd": "Atari",
  "Atari Lynx": "Atari",

  "Neo Geo Cd": "SNK",
  "Neo Geo Pocket": "SNK",

  "Pc Engine Turbografx 16": "NEC",
  "Pc Engine Cd Turbografx Cd": "NEC",
  "Pc Fx": "NEC",
  "Pc 8000 8800": "NEC",
};

export function companyOf(consoleName: string): Company {
  return COMPANY_BY_CONSOLE[consoleName] ?? "Otros";
}
