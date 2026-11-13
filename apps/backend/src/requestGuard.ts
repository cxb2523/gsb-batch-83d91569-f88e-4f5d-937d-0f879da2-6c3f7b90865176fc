import { timingSafeEqual } from "node:crypto";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { API_TOKEN_HEADER } from "../../../shared/constants";

// What the renderer may load: its own code and styles (inline styles for React style props), images
// from IGDB, YouTube thumbnails and SteamGridDB, and the privacy-enhanced YouTube player. Nothing else.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://images.igdb.com https://i.ytimg.com https://*.steamgriddb.com",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-src https://www.youtube-nocookie.com",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'"
].join("; ");

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

// GET routes the page loads through <img> or navigation, which cannot carry a header. They only return
// images or the app shell, and a foreign page can show an image but never read its pixels.
const PUBLIC_GETS = [/^\/$/, /^\/assets\//, /^\/api\/wallpaper\/current(\?|$)/, /^\/api\/artworks\/local\//, /^\/api\/covers\//];

// The local backend answers only this app:
// - the Host header must be a loopback name, so a web page that DNS-rebinds its own domain to
//   127.0.0.1 is refused;
// - /api calls must carry the random per-launch token the desktop app hands the renderer, so other
//   web pages and local programs cannot read or change data. Without a token (development) only the
//   host check applies.
export function installRequestGuard(app: FastifyInstance, { apiToken }: { apiToken?: string }) {
  const expected = apiToken ? Buffer.from(apiToken) : null;

  app.addHook("onSend", async (_request, reply) => {
    reply.header("content-security-policy", CONTENT_SECURITY_POLICY);
    reply.header("x-content-type-options", "nosniff");
  });

  app.addHook("onRequest", async (request, reply) => {
    if (!isLoopbackHost(request.headers.host)) return reply.code(403).send({ error: "Forbidden host" });
    if (!expected || !needsToken(request)) return;
    const given = request.headers[API_TOKEN_HEADER];
    const provided = Buffer.from(typeof given === "string" ? given : "");
    if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
      return reply.code(401).send({ error: "Missing or invalid app token" });
    }
  });
}

function isLoopbackHost(host: string | undefined) {
  if (!host) return false;
  const name = host.startsWith("[") ? host.slice(0, host.indexOf("]") + 1) : host.replace(/:\d+$/, "");
  return LOOPBACK_HOSTS.has(name.toLowerCase());
}

function needsToken(request: FastifyRequest) {
  if (!request.url.startsWith("/api/")) return false;
  const isRead = request.method === "GET" || request.method === "HEAD";
  return !(isRead && PUBLIC_GETS.some(pattern => pattern.test(request.url)));
}
