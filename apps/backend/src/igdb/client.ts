import { IGDB_REQUESTS_PER_SECOND } from "../../../../shared/constants";
import { refreshAccessToken, type TokenConfig } from "./token";

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
// Resolved per call so tests that stub the global fetch still reach a long-lived client.
const globalFetch: typeof fetch = (input, init) => globalThis.fetch(input, init);
// A hung IGDB request would otherwise leave sync, search or a Randomizer spin waiting forever.
const IGDB_REQUEST_TIMEOUT_MS = 10_000;

export class IgdbClient {
  private nextSlotAt = 0;
  private token: Promise<string | undefined> | undefined;

  constructor(
    private readonly config: TokenConfig,
    private readonly fetcher: typeof fetch = globalFetch,
    private readonly timeoutMs = IGDB_REQUEST_TIMEOUT_MS
  ) {}

  query<T>(endpoint: string, body: string): Promise<T[]> {
    return this.request<T[]>(endpoint, body);
  }

  // Any IGDB response shape: `games/count` answers with one `{ count }` object, not an array.
  async request<T>(endpoint: string, body: string): Promise<T> {
    const clientId = this.config.clientId;
    const initialToken = await this.getToken();
    if (!clientId || !initialToken) throw new Error("IGDB credentials missing");
    let token = initialToken;
    for (let attempt = 0; attempt < 3; attempt++) {
      await this.rateLimit();
      const response = await this.send(endpoint, clientId, token, body);
      if (response.status === 429) {
        await delay(500 * (attempt + 1));
        continue;
      }
      if ((response.status === 401 || response.status === 403) && this.config.clientSecret && attempt === 0) {
        const refreshed = await this.getToken(true);
        if (!refreshed) throw new Error("IGDB credentials missing");
        token = refreshed;
        continue;
      }
      if (!response.ok) throw new Error(`IGDB ${endpoint} failed: ${response.status}`);
      return await response.json() as T;
    }
    throw new Error("IGDB rate limit retry exhausted");
  }

  // A timeout is a plain failed request: only 429 responses are retried.
  private async send(endpoint: string, clientId: string, token: string, body: string) {
    try {
      return await this.fetcher(`https://api.igdb.com/v4/${endpoint}`, {
        method: "POST",
        headers: {
          "Client-ID": clientId,
          Authorization: `Bearer ${token}`,
          Accept: "application/json"
        },
        body,
        signal: AbortSignal.timeout(this.timeoutMs)
      });
    } catch (error) {
      if (error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError")) {
        throw new Error(`IGDB ${endpoint} timed out after ${this.timeoutMs} ms`);
      }
      throw error;
    }
  }

  // Concurrent callers share one token request.
  private getToken(forceRefresh = false) {
    if (this.token && !forceRefresh) return this.token;
    this.token = this.config.clientSecret
      ? refreshAccessToken(this.config, this.fetcher)
      : Promise.resolve(this.config.accessToken);
    this.token.catch(() => { this.token = undefined; });
    return this.token;
  }

  // Slots are reserved synchronously, so concurrent callers are spaced out instead of racing.
  private async rateLimit() {
    const minGap = Math.ceil(1000 / IGDB_REQUESTS_PER_SECOND);
    const now = Date.now();
    const slot = Math.max(now, this.nextSlotAt);
    this.nextSlotAt = slot + minGap;
    if (slot > now) await delay(slot - now);
  }
}
