// An anonymous visitor id in the OpenUI docs chat's format (docs/lib/openui-cloud/user-id.ts):
// `openui_<demo>_<uuid v4>`, sent in the same header. It's kept under its own sessionStorage key:
// on openui.com the demo shares an origin with the docs chat, which would overwrite a shared one. There's no sign-in: the browser makes up an id once per tab session and sends it when
// asking for a frontend token, and Gateway scopes that token to the id, so each visitor lists and
// opens only their own threads. The demo prefix keeps this demo's visitors apart in Gateway's
// logs. It separates visitors; it doesn't prove who anyone is.

export const USER_ID_HEADER = "x-openui-cloud-user-id";

const STORAGE_KEY = "openui-f1-user-id";
const PREFIX = "openui_f1_";
const PATTERN = /^openui_f1_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const isUserId = (value: string | null): value is string => value !== null && PATTERN.test(value);

/** Server: the visitor id from the request, or null when it's missing or malformed. */
export function readUserId(request: Request): string | null {
  const id = request.headers.get(USER_ID_HEADER);
  return isUserId(id) ? id : null;
}

/** Browser: this tab session's visitor id, made on first use. */
export function getOrCreateUserId(): string {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (isUserId(stored)) return stored;
  } catch {
    // Storage unavailable: use a fresh id for this page load.
  }
  const id = `${PREFIX}${crypto.randomUUID()}`;
  try {
    sessionStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Continue with the generated id when browser storage is unavailable.
  }
  return id;
}
