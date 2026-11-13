import { frontendToken } from "../../../lib/frontend-token";
import { hasAllowedOrigin } from "../../../lib/same-origin";
import { readUserId } from "../../../lib/user-id";

export const runtime = "nodejs";

// Mints the short-lived frontend token that useOpenuiCloudStorage() sends with its
// Conversations API calls. Gateway scopes the token to the visitor's anonymous id and this app,
// so each browser reaches only its own threads and never sees THESYS_API_KEY.
export async function POST(request: Request) {
  if (!hasAllowedOrigin(request))
    return Response.json(
      { error: "This example only accepts requests from its local chat interface." },
      { status: 403 },
    );
  const userId = readUserId(request);
  if (!userId) return Response.json({ error: "Missing visitor id." }, { status: 401 });
  const apiKey = process.env.THESYS_API_KEY;
  if (!apiKey) throw new Error("Set THESYS_API_KEY in .env.local, then restart.");

  try {
    const { token, expiresAt } = await frontendToken(apiKey, userId, request.signal);
    return Response.json(
      { token, expires_at: expiresAt },
      { headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return Response.json({ error: "OpenUI Gateway could not create a frontend token." }, { status: 502 });
  }
}
