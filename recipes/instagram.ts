/**
 * Instagram Reel posting, as a first-class veil recipe.
 *
 * Everything here was learned the hard way on 2026-07-31, after a one-shot script had been
 * failing with "ABORT: no Create control" for days. The account was never logged out — the
 * script was simply wrong about the UI. Each constant below encodes one of those findings, so
 * nobody rediscovers them:
 *
 *   1. The sidebar control is labelled "New post", NOT "Create". A script matching /create/i
 *      finds nothing and concludes it is signed out.
 *   2. A "Turn on notifications" dialog frequently covers the sidebar. Until it is dismissed,
 *      veil correctly refuses every click as "covered by <div>" — which reads like a broken
 *      selector but is an overlay.
 *   3. "New post" opens a submenu with TWO entries: Post and Live video. They are ~44px apart
 *      and picking blind lands you in the Live-video composer, which looks plausible and posts
 *      nothing. Always resolve the entry by its LABEL.
 *   4. The wizard is crop -> Next -> edit -> Next -> caption -> Share -> Done. Share is not the
 *      end: Instagram aborts the upload if the tab closes before "Done" appears (~20-35s).
 *   5. The caption box is a contenteditable, so it must be TYPED. Setting .value or .innerText
 *      leaves React's state empty and the reel posts with no caption.
 *
 * Every run writes ONE machine-readable record (see recipes/run-report.ts): platform, the
 * original page URL (Instagram's home page — which is where the run starts), the outcome
 * (published / dry_run / failed), the stage it stopped or failed in, stage durations, the
 * original error, and a page-text summary on failure. A thrown stage aborts the platform's
 * flow but the ORIGINAL error is re-thrown (never swallowed) and the page is always closed in
 * `finally`.
 *
 * Usage:
 *   const result = await postInstagramReel(browser, { file, caption });
 *   result.outcome // "published" | "dry_run" | "failed"
 */
import type { Browser } from "../src/browser.ts";
import { RecipeRun, RUN_STAGES, summarizePage, type RunRecord } from "./run-report.ts";

/** Instagram's home page — the run's original page, recorded in the result. */
export const INSTAGRAM_HOME = "https://www.instagram.com/";

export interface ReelOptions {
  /** Absolute path to a 9:16 mp4. */
  file: string;
  caption: string;
  /** Set false to stop before the irreversible Share click (dry run). */
  publish?: boolean;
  log?: (msg: string) => void;
  /** Override the result file (defaults to VEIL_RECIPE_RESULTS, then .veil-results/). */
  resultFile?: string;
  /**
   * TEST-ONLY wait hook: replaces the recipe's fixed waits (so a local fixture page does not
   * pay the real-site's 5s polling). It must NOT change control flow or any decision.
   */
  wait?: (ms: number) => Promise<void>;
  /**
   * TEST-ONLY start URL override (defaults to Instagram's home page, INSTAGRAM_HOME).
   * The record always names the URL the run actually started from.
   */
  homeUrl?: string;
}

type Wait = (ms: number) => Promise<void>;
const realSleep: Wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function elements(page: any): Promise<any[]> {
  const s: any = await page.snapshot();
  return s.elements ?? s;
}

async function clickNamed(page: any, rx: RegExp, what: string, sleep: Wait, tries = 8): Promise<boolean> {
  for (let i = 0; i < tries; i++) {
    const hit = (await elements(page)).find((e) => rx.test(String(e.name ?? "").trim()));
    if (hit) {
      try {
        await page.click(hit.ref);
        return true;
      } catch {
        // Covered or off-screen. Scroll and re-snapshot — refs are invalidated by a scroll.
        await page.scroll(0, 240);
        await sleep(600);
      }
    } else {
      await sleep(1200);
    }
  }
  return false;
}

/** Dismiss the overlays Instagram throws up, which otherwise block every subsequent click. */
async function dismissOverlays(page: any, log: (m: string) => void, sleep: Wait): Promise<void> {
  for (const label of [/^Not Now$/i, /^Not now$/i, /^Allow all cookies$/i, /^Decline optional/i]) {
    if (await clickNamed(page, label, "overlay", sleep, 2)) {
      log(`dismissed overlay: ${label}`);
      await sleep(1500);
    }
  }
}

/**
 * Run the Instagram flow and return its record on success/dry-run.
 *
 * A stage that throws is recorded (outcome "failed", its stage, the ORIGINAL message, a page
 * summary) and that SAME original error is then re-thrown — the record does not replace it, and
 * the page is still closed in `finally`.
 */
export async function postInstagramReel(browser: Browser, opts: ReelOptions): Promise<RunRecord> {
  const log = opts.log ?? ((m: string) => console.log("  " + m));
  const sleep: Wait = opts.wait ?? realSleep;
  const homeUrl = opts.homeUrl ?? INSTAGRAM_HOME;
  const run = new RecipeRun({
    platform: "instagram",
    pageUrl: homeUrl,
    publish: opts.publish !== false,
    resultFile: opts.resultFile,
    log,
  });
  let page: any = null;
  try {
    run.enter(RUN_STAGES.prepare);
    page = await (browser as any).newPage();

    run.enter(RUN_STAGES.loadPage);
    await page.setViewport({ width: 1500, height: 1300 }).catch(() => {});
    await page.goto(homeUrl, { timeout: 60000 });
    await sleep(8000);
    await dismissOverlays(page, log, sleep);

    run.enter(RUN_STAGES.openEditor);
    // (1) The control is "New post". Locate it by aria-label on the svg, then click its centre —
    // the accessible name lives on the icon, not the anchor.
    const np = await page.evaluate(`(()=>{
      for (const el of document.querySelectorAll('svg[aria-label]')) {
        if ((el.getAttribute('aria-label')||'') === 'New post') {
          const t = el.closest('a,div[role=button],span') || el;
          const r = t.getBoundingClientRect();
          return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
        }
      }
      return null; })()`);
    if (!np) throw new Error('Instagram: no "New post" control (it is NOT called "Create")');
    await page.clickAt(np.x, np.y);
    await sleep(3500);

    // (3) Resolve Post vs Live video BY LABEL. Never by position.
    const items = await page.evaluate(`(()=>{
      const out = [];
      for (const el of document.querySelectorAll('div[role="button"],a,span')) {
        const t = (el.innerText||'').trim();
        if (/^(Post|Reel|Live video)$/i.test(t)) {
          const r = el.getBoundingClientRect(); if (r.width < 10) continue;
          out.push({ t, x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) });
        }
      }
      const seen = {}; return out.filter(o => { const k=o.t.toLowerCase(); if(seen[k]) return false; seen[k]=1; return true; });
    })()`);
    const post = items.find((i: any) => /^post$/i.test(i.t));
    if (!post) throw new Error(`Instagram: no "Post" entry in the create menu (saw: ${items.map((i: any) => i.t).join(", ")})`);
    log(`create menu: ${items.map((i: any) => i.t).join(", ")} — choosing Post`);
    await page.clickAt(post.x, post.y);
    await sleep(5000);

    run.enter(RUN_STAGES.attach);
    const hasInput = await page.evaluate(`!!document.querySelector('input[type=file]')`);
    if (!hasInput) throw new Error("Instagram: upload dialog has no file input");
    await page.uploadFile([opts.file]);
    log("file handed to input");
    await sleep(12000);

    run.enter(RUN_STAGES.editorSteps);
    // (4) crop -> Next, edit -> Next.
    for (const step of ["crop", "edit"]) {
      if (!(await clickNamed(page, /^Next$/i, `Next (${step})`, sleep))) throw new Error(`Instagram: no Next at the ${step} step`);
      log(`advanced past ${step}`);
      await sleep(5000);
    }

    run.enter(RUN_STAGES.captionVerify);
    // (5) The caption is a contenteditable — type it, then VERIFY, because a silent failure
    // here posts a reel with no caption and that cannot be undone from this flow.
    const box = (await elements(page)).find((e) => /write a caption/i.test(String(e.name ?? "")));
    if (!box) throw new Error("Instagram: no caption box at the share step");
    await page.click(box.ref);
    await sleep(1200);
    for (const chunk of opts.caption.match(/[\s\S]{1,40}/g) ?? []) {
      await page.type(chunk);
      await sleep(160);
    }
    await sleep(2500);
    const landed = await page.evaluate(`[...document.querySelectorAll('[contenteditable="true"]')].map(e=>(e.innerText||'').trim()).filter(Boolean)`);
    const norm = (s: string) => s.replace(/\s+/g, " ").trim();
    if (!landed.some((c: string) => norm(c).includes(norm(opts.caption).slice(0, 40))))
      throw new Error("Instagram: caption did not land in the editor — refusing to post captionless");
    log("caption verified in the editor");

    if (opts.publish === false) {
      log("dry run — stopping before Share");
      run.dryRun(RUN_STAGES.publishConfirm);
      return run.record()!;
    }

    run.enter(RUN_STAGES.publishConfirm);
    if (!(await clickNamed(page, /^Share$/i, "Share", sleep))) throw new Error("Instagram: no Share button");
    log("shared — waiting for Done (Instagram aborts if the tab closes first)");

    run.enter(RUN_STAGES.postPublishVerify);
    // Poll for Done rather than sleeping a fixed time; upload duration varies with file size.
    let done = false;
    for (let i = 0; i < 12; i++) {
      await sleep(5000);
      if ((await elements(page)).some((e) => /^Done$/i.test(String(e.name ?? "").trim()))) {
        done = true;
        break;
      }
    }
    if (!done) throw new Error("Instagram: never reached Done — treat the post as UNCONFIRMED and check the profile");
    await clickNamed(page, /^Done$/i, "Done", sleep, 3);
    log("posted");
    run.published();
    return run.record()!;
  } catch (e: any) {
    // Record the failure with the ORIGINAL message, then re-throw that same original error —
    // a stage throw aborts this platform's flow and must not be swallowed.
    const error = String(e?.message ?? e);
    const record = run.failed(error, await summarizePage(page));
    log(`failed at stage ${record?.stage ?? "unknown"}: ${error}`);
    throw e;
  } finally {
    // Deliberately NOT closing the page on the success path before Done — see (4).
    await page?.close().catch(() => {});
  }
}
