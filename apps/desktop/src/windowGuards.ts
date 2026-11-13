import type { WebContents } from "electron";

type NavigationDecision = "allow" | "external" | "block";

// Where a URL the app window tries to show should go: the app's own pages stay in the window,
// web links open in the user's browser, and every other scheme (file:, javascript:, custom
// protocols) is refused. The app window must never show someone else's page, because it carries
// the preload bridge and the backend's API token.
export function decideNavigation(url: string, appOrigin: string): NavigationDecision {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "block";
  }
  // Compared by scheme and host: a custom scheme's URL.origin is "null", which would match any other.
  const app = appOrigin ? new URL(appOrigin) : null;
  if (app && parsed.protocol === app.protocol && parsed.host === app.host) return "allow";
  return parsed.protocol === "https:" || parsed.protocol === "http:" ? "external" : "block";
}

export function installWindowGuards(
  contents: Pick<WebContents, "setWindowOpenHandler" | "on">,
  { appOrigin, openExternal }: { appOrigin: () => string; openExternal: (url: string) => Promise<unknown> }
) {
  const sendOut = (url: string) => {
    if (decideNavigation(url, appOrigin()) === "external") void openExternal(url).catch(() => undefined);
  };
  contents.setWindowOpenHandler(({ url }) => {
    sendOut(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (decideNavigation(url, appOrigin()) === "allow") return;
    event.preventDefault();
    sendOut(url);
  });
}
