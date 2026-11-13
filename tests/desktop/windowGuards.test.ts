import { describe, expect, test, vi } from "vitest";
import { decideNavigation, installWindowGuards } from "../../apps/desktop/src/windowGuards";

const app = "http://127.0.0.1:41234";

describe("window guards", () => {
  test("the app's own pages stay in the window; web links go to the browser; anything else is blocked", () => {
    expect(decideNavigation(`${app}/`, app)).toBe("allow");
    expect(decideNavigation(`${app}/?view=detail`, app)).toBe("allow");
    expect(decideNavigation("https://www.igdb.com/games/elden-ring", app)).toBe("external");
    expect(decideNavigation("http://example.com/page", app)).toBe("external");
    expect(decideNavigation("http://127.0.0.1:9999/other-local-server", app)).toBe("external");
    expect(decideNavigation("file:///C:/Windows/System32/", app)).toBe("block");
    expect(decideNavigation("javascript:alert(1)", app)).toBe("block");
    expect(decideNavigation("not a url", app)).toBe("block");
  });

  test("new windows are never opened in the app; web links open in the browser instead", () => {
    const handlers: Record<string, (...args: never[]) => unknown> = {};
    let openHandler: ((details: { url: string }) => { action: string }) | undefined;
    const openExternal = vi.fn(async () => undefined);
    const contents = {
      setWindowOpenHandler: (handler: typeof openHandler) => { openHandler = handler; },
      on: (event: string, handler: (...args: never[]) => unknown) => { handlers[event] = handler; }
    };

    installWindowGuards(contents as never, { appOrigin: () => app, openExternal });

    expect(openHandler!({ url: "https://www.igdb.com/games/hades" })).toEqual({ action: "deny" });
    expect(openHandler!({ url: "file:///etc/passwd" })).toEqual({ action: "deny" });
    expect(openExternal).toHaveBeenCalledTimes(1);
    expect(openExternal).toHaveBeenCalledWith("https://www.igdb.com/games/hades");

    const preventDefault = vi.fn();
    (handlers["will-navigate"] as (event: { preventDefault(): void }, url: string) => void)({ preventDefault }, "https://www.igdb.com/games/hades");
    expect(preventDefault).toHaveBeenCalled();
    expect(openExternal).toHaveBeenCalledTimes(2);

    const stay = vi.fn();
    (handlers["will-navigate"] as (event: { preventDefault(): void }, url: string) => void)({ preventDefault: stay }, `${app}/`);
    expect(stay).not.toHaveBeenCalled();
  });
});
