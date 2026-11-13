// @vitest-environment jsdom
import { describe, expect, test } from "vitest";
import { installImageFallback } from "../../apps/frontend/src/ui/imageFallback";

describe("image fallback", () => {
  test("an image that fails to load is marked, so its frame shows empty instead of a broken-image icon", () => {
    const root = document.createElement("div");
    installImageFallback(root);
    const image = document.createElement("img");
    root.append(image);

    image.dispatchEvent(new Event("error"));
    expect(image.hasAttribute("data-image-failed")).toBe(true);

    // The same element reused for a new cover that loads is shown again.
    image.dispatchEvent(new Event("load"));
    expect(image.hasAttribute("data-image-failed")).toBe(false);
  });

  test("errors from other elements are left alone", () => {
    const root = document.createElement("div");
    installImageFallback(root);
    const frame = document.createElement("iframe");
    root.append(frame);

    frame.dispatchEvent(new Event("error"));
    expect(frame.hasAttribute("data-image-failed")).toBe(false);
  });
});
