import { describe, expect, test } from "bun:test";
import { extractFromHtml, createTestDom } from "./test-dom.ts";
import {
  extractUrlsWithTrace,
  extractVisibleUrls,
  parseAndNormalize,
} from "./url-extract.ts";
import type { UrlCandidateRecord, UrlCandidateStatus } from "./schemas.ts";

const JS_URL = `java${"script"}:void(0)`;

const BASE_PAGE = `<!doctype html>
<html>
  <head>
    <base href="https://example.com/section/page" />
    <link rel="canonical" href="https://example.com/canonical" />
    <meta name="og:url" content="https://example.com/og" />
    <script src="https://cdn.example.com/head.js"></script>
  </head>
  <body>
    <main>
      <a id="rel" href="../about">About</a>
      <a id="mail" href="mailto:user@example.com">Mail</a>
      <a id="js" href="${JS_URL}">JS</a>
      <a id="abs" href="https://shop.example.com/item">Shop</a>
      <div id="hidden-box" hidden>
        <a id="hidden-link" href="https://hidden.example.com/">Hidden</a>
      </div>
      <a id="dup-1" href="https://dup.example.com/">Dup</a>
      <a id="dup-2" href="https://dup.example.com/">Dup again</a>
      <img id="img" src="/assets/logo.png" alt="logo" />
      <p id="text-para">
        Read more at https://inline.example.com/article right now.
      </p>
    </main>
  </body>
</html>`;

function byRaw(
  candidates: UrlCandidateRecord[],
  needle: string,
): UrlCandidateRecord {
  const match = candidates.find((c) => c.rawValue === needle);
  if (!match) {
    throw new Error(
      `no candidate with rawValue ${JSON.stringify(needle)}; got: ${candidates
        .map(
          (c) =>
            `${c.sourceCategory}:${JSON.stringify(c.rawValue)}:${c.status}`,
        )
        .join(", ")}`,
    );
  }
  return match;
}

function byStatus(
  candidates: UrlCandidateRecord[],
  status: UrlCandidateStatus,
): UrlCandidateRecord[] {
  return candidates.filter((c) => c.status === status);
}

describe("relative link resolution", () => {
  test("relative href resolves against the document base and is included", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const candidate = byRaw(result.candidates, "../about");
    expect(candidate.status).toBe("included");
    expect(candidate.sourceCategory).toBe("anchor");
    expect(candidate.url).toBe("https://example.com/about");
    expect(candidate.domain).toBe("example.com");
    expect(candidate.reason).toBe("Collected");

    const included = result.urls.find((r) => r.url === candidate.url);
    expect(included).toBeDefined();
    expect(included?.count).toBe(1);
  });

  test("root-relative media src resolves in comprehensive mode", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "comprehensive",
    });
    const candidate = byRaw(result.candidates, "/assets/logo.png");
    expect(candidate.status).toBe("included");
    expect(candidate.sourceCategory).toBe("media");
    expect(candidate.url).toBe("https://example.com/assets/logo.png");
  });
});

describe("non-http(s) schemes are rejected", () => {
  test("mailto and javascript candidates are recorded as parseFailed", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const mailto = byRaw(result.candidates, "mailto:user@example.com");
    expect(mailto.status).toBe("parseFailed");
    expect(mailto.url).toBeNull();
    expect(mailto.domain).toBeNull();
    expect(mailto.reason).toContain("mailto:");

    const js = byRaw(result.candidates, JS_URL);
    expect(js.status).toBe("parseFailed");
    expect(js.url).toBeNull();
    expect(js.reason).toContain("not allowed");

    // Rejected candidates never enter the accepted list.
    expect(result.urls.map((r) => r.url)).not.toContain(
      "mailto:user@example.com",
    );
    expect(result.urls.map((r) => r.url)).not.toContain(JS_URL);
  });

  test("empty and unparseable values count as parse failures too", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body><a href="   ">blank</a><a href="https://">broken</a></body></html>`;
    const result = extractFromHtml({
      html,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const failures = byStatus(result.candidates, "parseFailed");
    expect(failures.length).toBe(2);
    expect(failures.every((c) => c.url === null)).toBe(true);
    expect(result.urls).toHaveLength(0);
  });

  test("parseAndNormalize still rejects the same schemes directly", () => {
    expect(parseAndNormalize("mailto:a@b.com", "https://x.com/")).toBeNull();
    expect(parseAndNormalize(JS_URL, "https://x.com/")).toBeNull();
  });
});

describe("visibility filtering", () => {
  test("hidden element is invisible in visible mode but included in all mode", () => {
    const visibleRun = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "visible",
      sourceMode: "anchors",
    });
    const hiddenInVisible = byRaw(
      visibleRun.candidates,
      "https://hidden.example.com/",
    );
    expect(hiddenInVisible.status).toBe("invisible");
    expect(hiddenInVisible.reason).toContain("hidden");
    expect(visibleRun.urls.map((r) => r.url)).not.toContain(
      "https://hidden.example.com/",
    );

    const allRun = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const hiddenInAll = byRaw(allRun.candidates, "https://hidden.example.com/");
    expect(hiddenInAll.status).toBe("included");
    expect(allRun.urls.map((r) => r.url)).toContain(
      "https://hidden.example.com/",
    );
  });

  test("aria-hidden ancestors are reported as invisible with a reason", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body><span aria-hidden="true"><a href="https://aria.example.com/">x</a></span></body></html>`;
    const result = extractFromHtml({
      html,
      visibilityMode: "visible",
      sourceMode: "anchors",
    });
    const candidate = byRaw(result.candidates, "https://aria.example.com/");
    expect(candidate.status).toBe("invisible");
    expect(candidate.reason).toContain("aria-hidden");
  });

  test("display:none from computed style is reported as invisible", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body><p class="none"><a href="https://css.example.com/">x</a></p></body></html>`;
    const result = extractFromHtml({
      html,
      visibilityMode: "visible",
      sourceMode: "anchors",
      computedStyles: { "p.none": { display: "none" } },
    });
    const candidate = byRaw(result.candidates, "https://css.example.com/");
    expect(candidate.status).toBe("invisible");
    expect(candidate.reason).toContain("display: none");
  });

  test("elements outside the viewport fail viewport mode only", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body><a id="below" href="https://below.example.com/">x</a></body></html>`;
    const opts = {
      html,
      sourceMode: "anchors" as const,
      rects: {
        "#below": { top: 2000, bottom: 2020, left: 0, right: 50 },
      },
      innerHeight: 768,
      innerWidth: 1024,
    };
    const viewportRun = extractFromHtml({
      ...opts,
      visibilityMode: "viewport",
    });
    const offscreen = byRaw(
      viewportRun.candidates,
      "https://below.example.com/",
    );
    expect(offscreen.status).toBe("invisible");
    expect(offscreen.reason).toContain("viewport");

    const visibleRun = extractFromHtml({
      ...opts,
      visibilityMode: "visible",
    });
    expect(
      byRaw(visibleRun.candidates, "https://below.example.com/").status,
    ).toBe("included");
  });
});

describe("head elements across source modes", () => {
  test("head link is skipped in comprehensive mode", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "comprehensive",
    });
    const canonical = byRaw(result.candidates, "https://example.com/canonical");
    expect(canonical.status).toBe("skipped");
    expect(canonical.sourceCategory).toBe("head");
    expect(canonical.reason).toContain("head");
    expect(result.urls.map((r) => r.url)).not.toContain(
      "https://example.com/canonical",
    );
  });

  test("head link, meta and script are included in everything mode", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "everything",
    });
    const canonical = byRaw(result.candidates, "https://example.com/canonical");
    expect(canonical.status).toBe("included");
    expect(canonical.sourceCategory).toBe("head");

    const meta = byRaw(result.candidates, "https://example.com/og");
    expect(meta.status).toBe("included");
    expect(meta.sourceCategory).toBe("meta");

    const script = byRaw(result.candidates, "https://cdn.example.com/head.js");
    expect(script.status).toBe("included");
    expect(script.sourceCategory).toBe("script");

    const accepted = result.urls.map((r) => r.url);
    expect(accepted).toContain("https://example.com/canonical");
    expect(accepted).toContain("https://example.com/og");
    expect(accepted).toContain("https://cdn.example.com/head.js");
  });

  test("everything-only sources are sourceDisabled in anchors mode", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const text = byRaw(result.candidates, "https://inline.example.com/article");
    expect(text.status).toBe("sourceDisabled");
    expect(text.sourceCategory).toBe("text");
    expect(text.reason).toContain("Anchors-only");

    const media = byRaw(result.candidates, "/assets/logo.png");
    expect(media.status).toBe("sourceDisabled");
    expect(media.sourceCategory).toBe("media");
  });
});

describe("duplicate counting", () => {
  test("repeated normalized URLs keep one record and count occurrences", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const dupes = byStatus(result.candidates, "duplicate");
    const secondCopy = byRaw(result.candidates, "https://dup.example.com/");
    // byRaw returns the first match; locate the duplicate trace row directly.
    const dupRows = result.candidates.filter(
      (c) => c.rawValue === "https://dup.example.com/",
    );
    expect(dupRows.map((r) => r.status)).toEqual(["included", "duplicate"]);
    expect(secondCopy.status).toBe("included");
    const duplicateRow = dupRows[1]!;
    expect(duplicateRow.url).toBe("https://dup.example.com/");
    expect(duplicateRow.occurrence).toBe(2);
    expect(dupes.length).toBe(1);

    const record = result.urls.find(
      (r) => r.url === "https://dup.example.com/",
    );
    expect(record).toBeDefined();
    expect(record?.count).toBe(2);

    // Exactly one included trace row per normalized URL.
    const includedForDup = result.candidates.filter(
      (c) => c.status === "included" && c.url === "https://dup.example.com/",
    );
    expect(includedForDup).toHaveLength(1);
  });

  test("counts accumulate across three or more occurrences", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body>
        <a href="https://x.example.com/a">1</a>
        <a href="https://x.example.com/a">2</a>
        <a href="https://x.example.com/a">3</a>
      </body></html>`;
    const result = extractFromHtml({
      html,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    expect(result.urls).toHaveLength(1);
    expect(result.urls[0]?.count).toBe(3);
    const dupes = byStatus(result.candidates, "duplicate");
    expect(dupes.map((d) => d.occurrence)).toEqual([2, 3]);
  });
});

describe("trace shape and ordering", () => {
  test("every candidate carries raw value, category, status and index", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "everything",
    });
    expect(result.candidates.length).toBeGreaterThan(0);
    result.candidates.forEach((candidate, i) => {
      expect(candidate.index).toBe(i);
      expect(typeof candidate.rawValue).toBe("string");
      expect(candidate.reason.length).toBeGreaterThan(0);
      expect(candidate.occurrence).toBeGreaterThanOrEqual(1);
      if (candidate.status === "included") {
        expect(candidate.url).not.toBeNull();
        expect(candidate.domain).not.toBeNull();
      }
    });
  });

  test("candidates are ordered by document position", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "anchors",
    });
    const order = result.candidates.map((c) => c.rawValue);
    expect(order.indexOf("../about")).toBeLessThan(
      order.indexOf("mailto:user@example.com"),
    );
    expect(order.indexOf("mailto:user@example.com")).toBeLessThan(
      order.indexOf(JS_URL),
    );
  });

  test("included trace URLs are exactly the accepted records", () => {
    const result = extractFromHtml({
      html: BASE_PAGE,
      visibilityMode: "all",
      sourceMode: "everything",
    });
    const includedUrls = byStatus(result.candidates, "included").map(
      (c) => c.url,
    );
    expect(includedUrls.sort()).toEqual(result.urls.map((r) => r.url).sort());
  });
});

describe("parity with extractVisibleUrls", () => {
  const modePairs = [
    ["all", "anchors"],
    ["visible", "comprehensive"],
    ["all", "comprehensive"],
    ["all", "everything"],
    ["viewport", "everything"],
  ] as const;

  test.each(modePairs)(
    "accepted list matches extractVisibleUrls for %s/%s",
    (visibilityMode, sourceMode) => {
      const dom = createTestDom({ html: BASE_PAGE });
      const legacy = extractVisibleUrls({
        root: dom.document,
        visibilityMode,
        sourceMode,
      });
      const traced = extractUrlsWithTrace({
        root: dom.document,
        visibilityMode,
        sourceMode,
      });
      expect(traced.urls).toEqual(legacy);
    },
  );
});

describe("empty pages", () => {
  test("no candidates yields an empty trace and explicit empty state", () => {
    const html = `<!doctype html><html><head><base href="https://example.com/"></head>
      <body><p>Nothing link-like here.</p></body></html>`;
    const result = extractFromHtml({
      html,
      visibilityMode: "visible",
      sourceMode: "everything",
    });
    expect(result.candidates).toHaveLength(0);
    expect(result.urls).toHaveLength(0);
  });
});
