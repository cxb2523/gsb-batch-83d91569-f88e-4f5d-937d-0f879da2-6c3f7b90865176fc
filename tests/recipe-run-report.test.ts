/**
 * Run-report tests for the Facebook / Instagram Reel recipes (local fixtures only).
 *
 * What is pinned here — the failure mode that motivated the change is a run that LOOKS like a
 * success (file never attached, caption never reached the editor, post never confirmed) while
 * the script runs to the end. So these tests drive the REAL recipes against self-made pages and
 * assert the machine-readable record says what actually happened:
 *
 *   - caption never lands  -> outcome "failed", stage "caption_verify", original error kept
 *   - preview never appears -> outcome "failed", stage "attachment_preview"
 *   - dry run              -> outcome "dry_run", NEVER "published", stops at publish_confirm
 *   - result directory      -> created automatically when missing
 *   - one platform failing  -> the other still runs and records its own outcome
 *   - the page is closed    -> even on the failure path (finally)
 *
 * INTEGRATION test (real headless Chrome), skips under CI. Every page is a data: URL, so there
 * is no network access. Run: bun test tests/recipe-run-report.test.ts
 */
import { describe, it, expect, beforeAll, afterAll } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Browser } from "../src/index.ts";
import { postFacebookReel } from "../recipes/facebook.ts";
import { postInstagramReel } from "../recipes/instagram.ts";
import { runRecipes } from "../recipes/run-batch.ts";
import { resolveResultFile, type RunRecord } from "../recipes/run-report.ts";
import { dataUrl, facebookFixture, instagramFixture, uploadPathFor } from "./fixtures/recipe-pages.ts";
import { findChrome } from "../src/launcher.js";

const TIMEOUT = 60_000;

let chromePath: string | null = null;
try { chromePath = findChrome(); } catch { /* no Chrome here */ }
// In the Chrome CI job a missing Chrome is a failure, not a skip (same rule as mcp-attach-e2e).
if (!chromePath && process.env.VEIL_REQUIRE_CHROME) throw new Error("VEIL_REQUIRE_CHROME is set but findChrome() found no Chrome");

/** Collapse every fixed wait to a few ms; control flow and decisions stay untouched. */
const fast = (_ms: number) => new Promise<void>((r) => setTimeout(r, 10));

const readRecords = (file: string): RunRecord[] =>
  readFileSync(file, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as RunRecord);

describe.skipIf(!!process.env.CI || !chromePath)("recipe run report (local fixtures)", () => {
  let browser: Browser;
  let dir: string;
  let video: string;
  let uploadPath: string;
  let seq = 0;

  beforeAll(async () => {
    dir = mkdtempSync(join(tmpdir(), "veil-recipe-report-"));
    video = join(dir, "reel.mp4");
    writeFileSync(video, "fixture video bytes");
    uploadPath = uploadPathFor(video);
    browser = await Browser.launch({ headless: true, chromePath: chromePath! });
  }, TIMEOUT);

  afterAll(async () => {
    await browser?.close();
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  /** A fresh result path under a directory that does NOT exist yet (covers auto-create). */
  const freshResultFile = () => join(dir, `runs-${++seq}`, "nested", "recipe-results.jsonl");

  // ── Facebook ───────────────────────────────────────────────────────────────

  it("facebook: caption not in the editor => failed, stage caption_verify, original error kept", async () => {
    const resultFile = freshResultFile();
    let thrown: any = null;
    try {
      await postFacebookReel(browser, {
        pageUrl: dataUrl(facebookFixture({ captionLands: false, reelsTabText: "never published" })),
        file: uploadPath,
        caption: "caption that will not stick",
        publish: true,
        resultFile,
        wait: fast,
      });
    } catch (e) {
      thrown = e;
    }
    // The stage throw aborts the platform flow and is re-thrown, not swallowed.
    expect(thrown).toBeInstanceOf(Error);
    expect(String(thrown.message)).toMatch(/caption did not land/);

    const records = readRecords(resultFile);
    expect(records.length).toBe(1); // one run -> exactly one record
    const [rec] = records;
    expect(rec.platform).toBe("facebook");
    expect(rec.outcome).toBe("failed");
    expect(rec.published).toBe(false);
    // Asked to publish anyway; a failed run is "failed", never a dry-run stop.
    expect(rec.dryRun).toBe(false);
    expect(rec.stage).toBe("caption_verify");
    expect(rec.error).toContain("caption did not land"); // ORIGINAL message, intact
    expect(rec.error).toBe(String(thrown.message));
    expect(typeof rec.pageExcerpt).toBe("string"); // compacted page body kept for diagnosis
    expect(rec.stages.map((s) => s.stage)).toContain("caption_verify");
  }, TIMEOUT);

  it("facebook: attachment preview never appears => failed at attachment_preview", async () => {
    const resultFile = freshResultFile();
    await expect(
      postFacebookReel(browser, {
        pageUrl: dataUrl(facebookFixture({ preview: false })),
        file: uploadPath,
        caption: "a caption that lands",
        publish: true,
        resultFile,
        wait: fast,
      }),
    ).rejects.toThrow(/no video preview/);

    const records = readRecords(resultFile);
    expect(records.length).toBe(1);
    const [rec] = records;
    expect(rec.outcome).toBe("failed");
    expect(rec.stage).toBe("attachment_preview");
    expect(rec.error).toMatch(/no video preview/);
    expect(rec.published).toBe(false);
  }, TIMEOUT);

  it("facebook: dry run stops before Post and is NEVER recorded as published", async () => {
    const resultFile = freshResultFile();
    const rec = await postFacebookReel(browser, {
      pageUrl: dataUrl(facebookFixture({ reelsTabText: "a caption that lands" })),
      file: uploadPath,
      caption: "a caption that lands",
      publish: false,
      resultFile,
      wait: fast,
    });

    expect(rec.outcome).toBe("dry_run");
    expect(rec.published).toBe(false);
    expect(rec.dryRun).toBe(true);
    expect(rec.stage).toBe("publish_confirm");
    expect(rec.error ?? null).toBeNull();

    const [written] = readRecords(resultFile);
    expect(written.outcome).toBe("dry_run");
    expect(written.published).toBe(false);
  }, TIMEOUT);

  it("facebook: a confirmed post on the Reels tab is recorded as published", async () => {
    const resultFile = freshResultFile();
    const caption = "reel confirmed";
    const rec = await postFacebookReel(browser, {
      pageUrl: dataUrl(facebookFixture({ reelsTabText: caption })),
      file: uploadPath,
      caption,
      publish: true,
      resultFile,
      wait: fast,
    });
    expect(rec.outcome).toBe("published");
    expect(rec.published).toBe(true);
    expect(rec.stage).toBeNull();
    expect(readRecords(resultFile)[0].outcome).toBe("published");
  }, TIMEOUT);

  // ── Instagram ──────────────────────────────────────────────────────────────

  it("instagram: caption not in the editor => failed, stage caption_verify, original error kept", async () => {
    const resultFile = freshResultFile();
    let thrown: any = null;
    try {
      await postInstagramReel(browser, {
        file: uploadPath,
        caption: "instagram caption that will not stick",
        publish: true,
        homeUrl: dataUrl(instagramFixture({ captionLands: false })),
        resultFile,
        wait: fast,
      });
    } catch (e) {
      thrown = e;
    }
    expect(thrown).toBeInstanceOf(Error);
    expect(String(thrown.message)).toMatch(/caption did not land in the editor/);

    const records = readRecords(resultFile);
    expect(records.length).toBe(1);
    const [rec] = records;
    expect(rec.platform).toBe("instagram");
    expect(rec.outcome).toBe("failed");
    expect(rec.stage).toBe("caption_verify");
    expect(rec.error).toBe(String(thrown.message));
    expect(rec.published).toBe(false);
  }, TIMEOUT);

  it("instagram: dry run stops before Share and is NEVER recorded as published", async () => {
    const resultFile = freshResultFile();
    const rec = await postInstagramReel(browser, {
      file: uploadPath,
      caption: "instagram dry run caption",
      publish: false,
      homeUrl: dataUrl(instagramFixture()),
      resultFile,
      wait: fast,
    });
    expect(rec.outcome).toBe("dry_run");
    expect(rec.published).toBe(false);
    expect(rec.dryRun).toBe(true);
    expect(rec.stage).toBe("publish_confirm");
    expect(readRecords(resultFile)[0].published).toBe(false);
  }, TIMEOUT);

  it("instagram: never reaching Done => failed at post_publish_verify, not published", async () => {
    const resultFile = freshResultFile();
    await expect(
      postInstagramReel(browser, {
        file: uploadPath,
        caption: "instagram caption that lands",
        publish: true,
        homeUrl: dataUrl(instagramFixture({ done: false })),
        resultFile,
        wait: fast,
      }),
    ).rejects.toThrow(/never reached Done/);

    const [rec] = readRecords(resultFile);
    expect(rec.outcome).toBe("failed");
    expect(rec.stage).toBe("post_publish_verify");
    expect(rec.published).toBe(false);
  }, TIMEOUT);

  // ── result file / directory ────────────────────────────────────────────────

  it("creates a missing result directory automatically", async () => {
    const resultFile = join(dir, "auto", "deeply", "nested", "done.jsonl");
    expect(existsSync(join(dir, "auto"))).toBe(false);

    await postInstagramReel(browser, {
      file: uploadPath,
      caption: "dir creation caption",
      publish: false,
      homeUrl: dataUrl(instagramFixture()),
      resultFile,
      wait: fast,
    });

    expect(existsSync(resultFile)).toBe(true);
    expect(readRecords(resultFile).length).toBe(1);
  }, TIMEOUT);

  it("falls back to the fixed .veil-results directory when no path is given", () => {
    const prev = process.env.VEIL_RECIPE_RESULTS;
    delete process.env.VEIL_RECIPE_RESULTS;
    try {
      expect(resolveResultFile()).toMatch(/[\\/]\.veil-results[\\/]recipe-results\.jsonl$/);
    } finally {
      if (prev !== undefined) process.env.VEIL_RECIPE_RESULTS = prev;
    }
  });

  it("honours VEIL_RECIPE_RESULTS as the result file path", () => {
    const prev = process.env.VEIL_RECIPE_RESULTS;
    process.env.VEIL_RECIPE_RESULTS = join(dir, "from-env", "env-results.jsonl");
    try {
      expect(resolveResultFile()).toBe(join(dir, "from-env", "env-results.jsonl"));
    } finally {
      if (prev === undefined) delete process.env.VEIL_RECIPE_RESULTS;
      else process.env.VEIL_RECIPE_RESULTS = prev;
    }
  });

  // ── page lifecycle ─────────────────────────────────────────────────────────

  it("closes the page in finally even when a stage threw", async () => {
    // Spy on the page handed to the recipe and record whether close() actually ran.
    const realNewPage = browser.newPage.bind(browser);
    const seen: Array<{ closed: boolean }> = [];
    (browser as any).newPage = async () => {
      const page: any = await realNewPage();
      const realClose = page.close.bind(page);
      const record = { closed: false };
      page.close = async () => { await realClose(); record.closed = true; };
      seen.push(record);
      return page;
    };
    const resultFile = freshResultFile();
    try {
      await expect(
        postFacebookReel(browser, {
          pageUrl: dataUrl(facebookFixture({ preview: false })),
          file: uploadPath,
          caption: "closes even on failure",
          publish: true,
          resultFile,
          wait: fast,
        }),
      ).rejects.toThrow(/no video preview/);
    } finally {
      (browser as any).newPage = realNewPage;
    }
    expect(seen.length).toBe(1);
    expect(seen[0].closed).toBe(true); // the finally block ran despite the throw
    expect(readRecords(resultFile)[0].stage).toBe("attachment_preview");
  }, TIMEOUT);

  // ── independence ───────────────────────────────────────────────────────────

  it("one platform failing does not stop the other: both records land, batch prints the file", async () => {
    const resultFile = freshResultFile();
    const lines: string[] = [];
    const out = await runRecipes(browser, {
      // Facebook fails at caption_verify…
      fbPageUrl: dataUrl(facebookFixture({ captionLands: false })),
      fbFile: uploadPath,
      fbCaption: "facebook caption that will not stick",
      // …Instagram still runs to a dry-run stop.
      igFile: uploadPath,
      igCaption: "instagram independent caption",
      igHomeUrl: dataUrl(instagramFixture()),
      publish: false,
      resultFile,
      wait: fast,
      log: (m) => lines.push(m),
    });

    expect(out.failures.length).toBe(1);
    // The ORIGINAL recipe error, kept intact (the recipe's messages already name the platform).
    expect(out.failures[0]).toMatch(/facebook: caption did not land/);

    const records = readRecords(resultFile);
    expect(records.length).toBe(2);
    const fb = records.find((r) => r.platform === "facebook")!;
    const ig = records.find((r) => r.platform === "instagram")!;
    expect(fb.outcome).toBe("failed");
    expect(fb.stage).toBe("caption_verify");
    expect(ig.outcome).toBe("dry_run");
    expect(ig.published).toBe(false);

    expect(out.lines.join("\n")).toContain(`results file: ${resultFile}`);
    expect(lines.join("\n")).toContain("── instagram ──"); // Instagram ran after Facebook failed
  }, TIMEOUT);
});
