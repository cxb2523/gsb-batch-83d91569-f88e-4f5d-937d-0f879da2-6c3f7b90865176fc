/**
 * Run the Facebook and Instagram Reel recipes as ONE batch, each platform independently.
 *
 * One platform failing (a stage throws, the browser closes, the page is wedged) must never stop
 * the other: each run is wrapped on its own and its outcome is taken from the recipe's record.
 * When everything is done, the location of the result file is printed, and the process exits
 * non-zero if either platform did not publish (a dry run is a deliberate stop, not a success).
 *
 * The result file may be set with VEIL_RECIPE_RESULTS (a file path). Unset, it goes to the fixed
 * `.veil-results/recipe-results.jsonl`; the directory is created on demand.
 *
 * Usage:
 *   VEIL_RECIPE_RESULTS=out/runs.jsonl bun run recipes/run-batch.ts \
 *     --fb-page-url https://www.facebook.com/profile.php?id=... \
 *     --fb-file ./reel.mp4 --fb-caption "..." \
 *     --ig-file ./reel.mp4 --ig-caption "..." [--dry-run]
 */
import { Browser, findChrome } from "../src/index.ts";
import { postFacebookReel } from "./facebook.ts";
import { postInstagramReel } from "./instagram.ts";
import { resolveResultFile, type RunRecord } from "./run-report.ts";

interface Args {
  fbPageUrl?: string;
  fbFile?: string;
  fbCaption?: string;
  igFile?: string;
  igCaption?: string;
  igHomeUrl?: string;
  dryRun: boolean;
  headless: boolean;
  chromePath?: string;
  resultFile?: string;
}

function parseArgs(argv: string[]): Args {
  const a: Args = { dryRun: false, headless: true };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => argv[++i];
    switch (arg) {
      case "--fb-page-url": a.fbPageUrl = next(); break;
      case "--fb-file": a.fbFile = next(); break;
      case "--fb-caption": a.fbCaption = next(); break;
      case "--ig-file": a.igFile = next(); break;
      case "--ig-caption": a.igCaption = next(); break;
      case "--ig-home-url": a.igHomeUrl = next(); break;
      case "--result-file": a.resultFile = next(); break;
      case "--chrome": a.chromePath = next(); break;
      case "--dry-run": a.dryRun = true; break;
      case "--headful": a.headless = false; break;
      default:
        if (arg.startsWith("--")) throw new Error(`unknown flag: ${arg}`);
    }
  }
  return a;
}

export interface BatchJob {
  fbPageUrl?: string;
  fbFile?: string;
  fbCaption?: string;
  igFile?: string;
  igCaption?: string;
  /** TEST-ONLY override of Instagram's start page (defaults to its home page). */
  igHomeUrl?: string;
  publish: boolean;
  resultFile: string;
  log?: (msg: string) => void;
  /** TEST-ONLY wait hook passed through to both recipes (see their option docs). */
  wait?: (ms: number) => Promise<void>;
}

export interface BatchOutcome {
  resultFile: string;
  records: RunRecord[];
  /** Original error messages from platforms whose recipe threw. */
  failures: string[];
  /** printf-friendly summary lines; also printed by main(). */
  lines: string[];
}

/**
 * Run both platforms, each in its own try/catch, against the SAME browser.
 * Exported separately from main() so the independence guarantee is testable without a CLI.
 */
export async function runRecipes(browser: Browser, job: BatchJob): Promise<BatchOutcome> {
  const say = job.log ?? ((_m: string) => {});
  const records: RunRecord[] = [];
  const failures: string[] = [];

  // ── Facebook: independent of Instagram below ──
  if (job.fbPageUrl && job.fbFile && job.fbCaption) {
    say("── facebook ──");
    try {
      records.push(await postFacebookReel(browser, {
        pageUrl: job.fbPageUrl,
        file: job.fbFile,
        caption: job.fbCaption,
        publish: job.publish,
        resultFile: job.resultFile,
        log: say,
        wait: job.wait,
      }));
    } catch (e: any) {
      // The recipe already wrote its own failed record and re-threw the ORIGINAL error.
      failures.push(String(e?.message ?? e));
    }
  } else {
    say("── facebook: skipped (needs --fb-page-url, --fb-file, --fb-caption) ──");
  }

  // ── Instagram: runs even when Facebook just failed ──
  if (job.igFile && job.igCaption) {
    say("── instagram ──");
    try {
      records.push(await postInstagramReel(browser, {
        file: job.igFile,
        caption: job.igCaption,
        homeUrl: job.igHomeUrl,
        publish: job.publish,
        resultFile: job.resultFile,
        log: say,
        wait: job.wait,
      }));
    } catch (e: any) {
      failures.push(String(e?.message ?? e));
    }
  } else {
    say("── instagram: skipped (needs --ig-file, --ig-caption) ──");
  }

  const lines: string[] = [];
  for (const r of records) {
    lines.push(`${r.platform}: ${r.outcome}${r.stage ? ` (stage: ${r.stage})` : ""} — ${r.totalMs}ms`);
  }
  for (const f of failures) lines.push(`error: ${f}`);
  lines.push(`results file: ${job.resultFile}`);

  return { resultFile: job.resultFile, records, failures, lines };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const resultFile = resolveResultFile(args.resultFile);
  const ranAnything = Boolean((args.fbPageUrl && args.fbFile && args.fbCaption) || (args.igFile && args.igCaption));

  let browser: Browser | null = null;
  let outcome: BatchOutcome | null = null;
  try {
    browser = await Browser.launch({
      headless: args.headless,
      chromePath: args.chromePath ?? findChrome(),
    });
    outcome = await runRecipes(browser, {
      fbPageUrl: args.fbPageUrl,
      fbFile: args.fbFile,
      fbCaption: args.fbCaption,
      igFile: args.igFile,
      igCaption: args.igCaption,
      igHomeUrl: args.igHomeUrl,
      publish: !args.dryRun,
      resultFile,
      log: (m) => console.log(m),
    });
  } finally {
    await browser?.close().catch(() => {});
  }

  console.log("");
  for (const line of outcome?.lines ?? [`results file: ${resultFile}`]) console.log(line);

  // Non-zero unless every platform that ran CONFIRMED its publish — a dry run is a deliberate
  // stop, not success. `--dry-run` with no platform args is just a usage error (nothing ran).
  const failed = ranAnything
    ? outcome === null
      || outcome.failures.length > 0
      || outcome.records.length === 0
      || outcome.records.some((r) => r.outcome !== "published")
    : true;
  if (failed) process.exitCode = 1;
}

// Only run the CLI when invoked directly (tests import runRecipes from this module).
if (import.meta.main) {
  main().catch((e) => {
    console.error(String(e?.message ?? e));
    process.exit(1);
  });
}
