import { describe, expect, test } from "vitest";
import { APP_ORIGIN, backendUrlFor, identifyAppToYouTube, YOUTUBE_REFERER } from "../../apps/desktop/src/appProtocol";
import { decideNavigation } from "../../apps/desktop/src/windowGuards";

const backend = "http://127.0.0.1:41234";

describe("app:// protocol", () => {
  test("the renderer's pages, assets and API calls go to the same path on the backend", () => {
    expect(backendUrlFor(`${APP_ORIGIN}/`, backend)).toBe(`${backend}/`);
    expect(backendUrlFor(`${APP_ORIGIN}/assets/index-abc.js`, backend)).toBe(`${backend}/assets/index-abc.js`);
    expect(backendUrlFor(`${APP_ORIGIN}/api/releases?search=persona&platform=PC`, backend)).toBe(`${backend}/api/releases?search=persona&platform=PC`);
  });

  test("any other app:// host is refused", () => {
    expect(backendUrlFor("app://other/api/releases", backend)).toBeNull();
    expect(backendUrlFor("not a url", backend)).toBeNull();
  });

  test("the window keeps the app's own app:// pages and blocks other custom-scheme pages", () => {
    expect(decideNavigation(`${APP_ORIGIN}/`, APP_ORIGIN)).toBe("allow");
    expect(decideNavigation(`${APP_ORIGIN}/?view=detail`, APP_ORIGIN)).toBe("allow");
    expect(decideNavigation("app://other/", APP_ORIGIN)).toBe("block");
    expect(decideNavigation("evil://renderer/", APP_ORIGIN)).toBe("block");
    expect(decideNavigation(`${backend}/`, APP_ORIGIN)).toBe("external");
    expect(decideNavigation("https://www.igdb.com/games/hades", APP_ORIGIN)).toBe("external");
  });

  test("YouTube embeds are told which app they are in, unless the request already says", () => {
    let filter: { urls: string[] } | undefined;
    let listener: ((details: { requestHeaders: Record<string, string> }, callback: (response: { requestHeaders: Record<string, string> }) => void) => void) | undefined;
    identifyAppToYouTube({ webRequest: { onBeforeSendHeaders: (f: typeof filter, l: typeof listener) => { filter = f; listener = l; } } } as never);
    const send = (requestHeaders: Record<string, string>) => {
      let sent: Record<string, string> = {};
      listener!({ requestHeaders }, response => { sent = response.requestHeaders; });
      return sent;
    };

    expect(filter).toEqual({ urls: ["https://www.youtube-nocookie.com/embed/*"] });
    expect(send({ Accept: "text/html" })).toEqual({ Accept: "text/html", Referer: YOUTUBE_REFERER });
    expect(send({ Referer: "http://127.0.0.1:5173/" }).Referer).toBe("http://127.0.0.1:5173/");
  });
});
