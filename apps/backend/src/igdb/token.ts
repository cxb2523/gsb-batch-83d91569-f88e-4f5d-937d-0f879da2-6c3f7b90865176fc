export interface TokenConfig {
  clientId?: string;
  clientSecret?: string;
  accessToken?: string;
}

export function readTokenConfig(env: NodeJS.ProcessEnv = process.env): TokenConfig {
  return {
    clientId: env.IGDB_CLIENT_ID,
    clientSecret: env.IGDB_CLIENT_SECRET,
    accessToken: env.IGDB_ACCESS_TOKEN
  };
}

export function getAppCredentialStatus(config: TokenConfig, lastError?: string | null) {
  if (!config.clientId || (!config.clientSecret && !config.accessToken)) return { status: "missing" as const };
  if (lastError && /expired|invalid|401|403|rejected/i.test(lastError)) return { status: "expired-or-rejected" as const, message: lastError };
  if (lastError) return { status: "configured-invalid" as const, message: lastError };
  return { status: "ready" as const };
}

export async function refreshAccessToken(config: TokenConfig, fetcher: typeof fetch = fetch) {
  if (!config.clientId || !config.clientSecret) throw new Error("Missing IGDB client id or secret");
  const url = new URL("https://id.twitch.tv/oauth2/token");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("client_secret", config.clientSecret);
  url.searchParams.set("grant_type", "client_credentials");
  const response = await fetcher(url, { method: "POST" });
  if (!response.ok) throw new Error(`IGDB token refresh failed: ${response.status}`);
  const body = await response.json() as { access_token: string };
  return body.access_token;
}
