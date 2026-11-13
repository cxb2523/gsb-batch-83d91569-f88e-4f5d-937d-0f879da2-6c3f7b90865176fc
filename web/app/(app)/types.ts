export interface Game {
  id: string;
  name: string;
  consoles: string[];
  versions: number;
  sample_rom_path: string | null;
  image_icon: string | null;
  achievements: number | null;
}

export interface ConsoleCount {
  name: string;
  count: number;
  icon_url: string | null;
}

export interface GamesResponse {
  success: boolean;
  items: Game[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  consoles: ConsoleCount[];
}

export interface VersionInfo {
  filename: string;
  region: string;
  is_hack: boolean;
  is_translation: boolean;
  is_original: boolean;
  priority: number;
}

export interface Version {
  hash: string;
  rom_path: string;
  info: VersionInfo;
}

export interface VersionsResponse {
  success: boolean;
  versions: Version[];
}

export interface SearchResult {
  success: boolean;
  download_url?: string;
  link_ok?: boolean;
  ra_recognized?: boolean;
  name?: string;
  console?: string;
  message?: string;
}

export interface WantToPlayResponse {
  success: boolean;
  items: Game[];
  total?: number;
  requested?: number;
  message?: string;
}

export interface RaConnectResponse {
  success: boolean;
  message?: string;
}

export interface RaStatusResponse {
  connected: boolean;
  username: string | null;
}

export interface RaProfile {
  success: boolean;
  avatar_url: string | null;
  total_points?: number;
  total_true_points?: number;
  motto?: string | null;
  message?: string;
}
