import { describe, expect, test } from "vitest";
import viteConfig from "../../vite.config";

describe("vite packaged renderer config", () => {
  test("uses relative asset URLs so Electron file:// loads bundled JS and CSS", () => {
    expect(viteConfig.base).toBe("./");
  });
});
