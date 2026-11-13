// Frontend tokens: short-lived Gateway credentials scoped to one visitor and this app. The browser
// uses them for its thread list, and the chat route uses them to read a thread *as the visitor*,
// so Gateway itself refuses a thread that isn't theirs.

export const FRONTEND_TOKEN_HEADER = "x-thesys-frontend-token";

const APP_ID = process.env.APP_ID || "f1-dashboard";
// Reuse a token until a minute before it expires; keep at most this many visitors' tokens.
const REFRESH_MARGIN_S = 60;
const MAX_CACHED = 1000;
const cache = new Map<string, { token: string; expiresAt: number }>();

export async function frontendToken(apiKey: string, userId: string, signal?: AbortSignal) {
  const cached = cache.get(userId);
  if (cached && cached.expiresAt - REFRESH_MARGIN_S > Date.now() / 1000) return cached;

  const response = await fetch("https://api.thesys.dev/v1/frontend-tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    // No sign-in: user_id is the browser's anonymous visitor id (lib/user-id.ts). Use the
    // signed-in user's id instead when you add authentication:
    // https://www.openui.com/docs/gateway/authentication
    body: JSON.stringify({ user_id: userId, app_id: APP_ID }),
    signal,
  });
  if (!response.ok) throw new Error(`Gateway could not create a frontend token: ${response.status}`);
  const { token, expires_at } = (await response.json()) as { token: string; expires_at: number };

  const entry = { token, expiresAt: expires_at };
  cache.delete(userId);
  cache.set(userId, entry);
  if (cache.size > MAX_CACHED) cache.delete(cache.keys().next().value!);
  return entry;
}
