import type { ReleaseArtwork } from "../../../../shared/types";

interface SteamGridDbSearchResponse {
  success?: boolean;
  data?: Array<{ id?: number; name?: string }>;
}

interface SteamGridDbGridResponse {
  success?: boolean;
  data?: Array<{ id?: number; url?: string; nsfw?: boolean; animated?: boolean }>;
}

export class SteamGridDbClient {
  constructor(private readonly apiKey: string | undefined, private readonly fetcher: typeof fetch = fetch) {}

  async findArtwork(title: string): Promise<ReleaseArtwork[]> {
    if (!this.apiKey?.trim() || !title.trim()) return [];
    const game = await this.findGame(title);
    if (!game?.id) return [];
    const grids = await this.getGrids(game.id);
    return grids
      .filter(grid => grid.id && grid.url && !grid.nsfw && !grid.animated && /\.(jpe?g|png|webp)(\?|$)/i.test(grid.url))
      .slice(0, 3)
      .map(grid => ({
        imageId: `steamgriddb-${grid.id}`,
        source: "steamgriddb" as const,
        url: grid.url
      }));
  }

  private async findGame(title: string) {
    const response = await this.fetchJson<SteamGridDbSearchResponse>(`https://www.steamgriddb.com/api/v2/search/autocomplete/${encodeURIComponent(title)}`);
    return response.data?.[0];
  }

  private async getGrids(gameId: number) {
    const url = new URL(`https://www.steamgriddb.com/api/v2/grids/game/${gameId}`);
    url.searchParams.set("dimensions", "600x900,342x482");
    url.searchParams.set("types", "static");
    url.searchParams.set("nsfw", "false");
    const response = await this.fetchJson<SteamGridDbGridResponse>(url.toString());
    return response.data ?? [];
  }

  private async fetchJson<T>(url: string): Promise<T> {
    const response = await this.fetcher(url, {
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        Accept: "application/json"
      }
    });
    if (!response.ok) throw new Error(`SteamGridDB request failed: ${response.status}`);
    return await response.json() as T;
  }
}
