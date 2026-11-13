import type { Net, Protocol, Session } from "electron";

// The packaged renderer's fixed origin. The backend's port changes every launch, so serving the
// renderer from http://127.0.0.1:<port> would give it a new origin each time and lose its localStorage
// and V8 code cache. app://renderer stays the same, and every request under it is passed to the backend.
export const APP_SCHEME = "app";
export const APP_ORIGIN = `${APP_SCHEME}://renderer`;

// Must run before the app is ready. `standard` + `secure` give the scheme a real origin (localStorage,
// same-origin fetch and canvas reads); `codeCache` lets V8 keep compiled scripts between launches.
export function registerAppScheme(protocol: Pick<Protocol, "registerSchemesAsPrivileged">) {
  protocol.registerSchemesAsPrivileged([
    { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true, codeCache: true, stream: true } }
  ]);
}

// The backend URL an app:// request stands for, or null for any host but the renderer's.
export function backendUrlFor(requestUrl: string, backendBaseUrl: string) {
  let url: URL;
  try {
    url = new URL(requestUrl);
  } catch {
    return null;
  }
  if (url.protocol !== `${APP_SCHEME}:` || url.host !== new URL(APP_ORIGIN).host) return null;
  return `${backendBaseUrl}${url.pathname}${url.search}`;
}

export function handleAppProtocol(protocol: Pick<Protocol, "handle">, net: Pick<Net, "fetch">, backendBaseUrl: () => string) {
  protocol.handle(APP_SCHEME, request => {
    const target = backendUrlFor(request.url, backendBaseUrl());
    if (!target) return new Response("Not found", { status: 404 });
    // The backend is reached as a plain same-origin request: module scripts and stylesheets arrive
    // in CORS mode with Origin: app://renderer, which net.fetch would otherwise turn into a failed
    // cross-origin request to the backend.
    const headers = new Headers(request.headers);
    for (const name of ["host", "origin", "referer"]) headers.delete(name);
    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    return net.fetch(target, { method: request.method, headers, body: hasBody ? request.body : null, duplex: "half" } as RequestInit);
  });
}

// YouTube refuses to play an embed that does not say which site or app it is on (player error 153), and
// Chromium sends no Referer from an app:// page. YouTube asks apps without a web origin to identify
// themselves with an https://<app id> Referer, so embed page loads carry this app's id.
export const YOUTUBE_REFERER = "https://io.github.hachi23.game-release-tracker/";

export function identifyAppToYouTube(session: Pick<Session, "webRequest">) {
  session.webRequest.onBeforeSendHeaders({ urls: ["https://www.youtube-nocookie.com/embed/*"] }, (details, callback) => {
    const requestHeaders = { ...details.requestHeaders };
    if (!requestHeaders.Referer) requestHeaders.Referer = YOUTUBE_REFERER;
    callback({ requestHeaders });
  });
}
