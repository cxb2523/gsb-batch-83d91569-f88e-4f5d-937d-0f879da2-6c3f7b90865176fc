/**
 * Machine-readable stage conclusions for the Facebook / Instagram Reel recipes.
 *
 * The recipes can look successful while nothing happened (the file never attached, the caption
 * never reached the editor, the post never appeared on the right tab). Terminal logs are gone
 * the moment the process ends, so an operator cannot tell afterwards WHERE a run stopped or
 * what the page looked like at that moment. Every run therefore appends ONE JSON line:
 *
 *   { platform, pageUrl, outcome, published, dryRun, stage, error, pageExcerpt,
 *     stages: [{ stage, ms }, ...], totalMs, startedAt, finishedAt }
 *
 * outcome is one of:
 *   "published" — the recipe's OWN post-publish verification passed (Reels tab / Done).
 *   "dry_run"   — stopped on purpose before the irreversible click. NEVER "published".
 *   "failed"    — a stage threw. `stage` names the stage it threw in and `error` keeps the
 *                 original message; `pageExcerpt` is the page's compacted body text.
 *
 * Stage ids are stable, machine-readable keys (the recipes pass the RUN_STAGES constants):
 *   prepare                 new page / browser setup
 *   load_page               navigation + overlay dismissal
 *   open_editor             open the composer / New post -> Post
 *   caption_verify          typing the caption and verifying it landed
 *   attach                  handing the file to the input
 *   attachment_preview      waiting for the video preview
 *   editor_steps            Instagram's crop -> Next -> edit -> Next
 *   publish_confirm         the irreversible Post / Share click
 *   post_publish_verify     confirming the post is actually live
 *
 * Results land in `VEIL_RECIPE_RESULTS` when set (a file path), else the fixed
 * `.veil-results/recipe-results.jsonl`; the directory is created on demand. Records are appended
 * as JSON Lines, one per run.
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export type RecipePlatform = "facebook" | "instagram";
export type RunOutcome = "published" | "dry_run" | "failed";

/** Stable stage ids shared by both recipes. */
export const RUN_STAGES = {
  prepare: "prepare",
  loadPage: "load_page",
  openEditor: "open_editor",
  captionVerify: "caption_verify",
  attach: "attach",
  attachmentPreview: "attachment_preview",
  editorSteps: "editor_steps",
  publishConfirm: "publish_confirm",
  postPublishVerify: "post_publish_verify",
} as const;

export interface StageTiming {
  stage: string;
  ms: number;
}

export interface RunRecord {
  platform: RecipePlatform;
  /** The page this run STARTED from: Facebook's Page URL, Instagram's home page. */
  pageUrl: string;
  outcome: RunOutcome;
  /** Convenience boolean, true ONLY for outcome "published" — a dry run is never this. */
  published: boolean;
  /**
   * true ONLY for outcome "dry_run": the run reached the stop point and deliberately stopped
   * before the irreversible click. A run that was ASKED to dry-run but failed earlier is
   * "failed", not a dry run — asking for a dry run is not itself a result.
   */
  dryRun: boolean;
  /** Stage the run failed in, or (for a dry run) stopped at. null when published. */
  stage: string | null;
  /** The ORIGINAL error message, untouched. Only set when outcome is "failed". */
  error: string | null;
  /** Page body text, whitespace-compacted and truncated. Only captured on failure. */
  pageExcerpt: string | null;
  /** Per-stage durations, in run order. */
  stages: StageTiming[];
  totalMs: number;
  startedAt: string;
  finishedAt: string;
}

/** Env var holding the result FILE path (not a directory). */
export const RESULT_FILE_ENV = "VEIL_RECIPE_RESULTS";
/** Fixed directory used when no env/option path is given. */
export const DEFAULT_RESULT_DIR = ".veil-results";
export const DEFAULT_RESULT_FILE = "recipe-results.jsonl";

/** Resolve the result file: explicit option > env var > the fixed default directory. */
export function resolveResultFile(explicit?: string): string {
  const target = (explicit ?? "").trim() || (process.env[RESULT_FILE_ENV] ?? "").trim()
    || join(DEFAULT_RESULT_DIR, DEFAULT_RESULT_FILE);
  return resolve(target);
}

/** Append one record as a JSON line, creating the file's directory when missing. */
export function appendRunRecord(record: RunRecord, explicitFile?: string): string {
  const file = resolveResultFile(explicitFile);
  mkdirSync(dirname(file), { recursive: true });
  appendFileSync(file, JSON.stringify(record) + "\n", "utf8");
  return file;
}

export interface RecipeRunOptions {
  platform: RecipePlatform;
  pageUrl: string;
  /** The mode the caller ASKED for (publish:false = dry run); informational only — the
   *  record's `dryRun` reflects what actually happened, not what was requested. */
  publish: boolean;
  resultFile?: string;
  log?: (msg: string) => void;
}

/**
 * Tracks one recipe run's stages and writes its single record exactly once.
 *
 * `enter(stage)` closes the previous stage and starts timing the next one. The final call
 * (`published` / `dryRun` / `failed`) closes the last stage and persists the record. Persistence
 * failures are logged, never thrown: a run's real outcome must not be replaced by an I/O error,
 * and in the failure path the ORIGINAL error is always the one the recipe re-throws.
 */
export class RecipeRun {
  private readonly startedMs = Date.now();
  private readonly startedAt = new Date(this.startedMs).toISOString();
  private readonly stages: StageTiming[] = [];
  private current: { stage: string; start: number } | null = null;
  private settled = false;
  private lastRecord: RunRecord | null = null;

  constructor(private readonly opts: RecipeRunOptions) {}

  /** Start a stage, closing the one in flight. */
  enter(stage: string): this {
    const now = Date.now();
    this.closeCurrent(now);
    this.current = { stage, start: now };
    return this;
  }

  /** The stage currently in flight (used for diagnostics); null between stages. */
  currentStage(): string | null {
    return this.current?.stage ?? null;
  }

  /** Confirmed live by the recipe's own verification. */
  published(): RunRecord | null {
    return this.settle("published", null, null, null);
  }

  /** Stopped on purpose before the irreversible click — never recorded as published. */
  dryRun(stage: string = RUN_STAGES.publishConfirm): RunRecord | null {
    const stopStage = stage || this.current?.stage || null;
    return this.settle("dry_run", stopStage, null, null);
  }

  /** A stage threw; `error` is the original message and `pageExcerpt` the page's body text. */
  failed(error: string, pageExcerpt: string | null): RunRecord | null {
    const stage = this.current?.stage ?? null;
    return this.settle("failed", stage, error, pageExcerpt);
  }

  /** The record settled for this run, or null if it has not settled yet. */
  record(): RunRecord | null {
    return this.lastRecord;
  }

  private closeCurrent(now = Date.now()): void {
    if (!this.current) return;
    this.stages.push({ stage: this.current.stage, ms: Math.max(0, now - this.current.start) });
    this.current = null;
  }

  private settle(
    outcome: RunOutcome,
    stage: string | null,
    error: string | null,
    pageExcerpt: string | null,
  ): RunRecord | null {
    if (this.settled) return this.lastRecord; // one run -> one record
    this.settled = true;
    const finishedAt = new Date();
    this.closeCurrent(finishedAt.getTime());

    const record: RunRecord = {
      platform: this.opts.platform,
      pageUrl: this.opts.pageUrl,
      outcome,
      published: outcome === "published",
      dryRun: outcome === "dry_run",
      stage,
      error: outcome === "failed" ? error : null,
      pageExcerpt: outcome === "failed" ? pageExcerpt : null,
      stages: this.stages,
      totalMs: Math.max(0, finishedAt.getTime() - this.startedMs),
      startedAt: this.startedAt,
      finishedAt: finishedAt.toISOString(),
    };
    this.lastRecord = record;

    try {
      const file = appendRunRecord(record, this.opts.resultFile);
      this.opts.log?.(`run record written to ${file}`);
      return record;
    } catch (e: any) {
      // Never mask the recipe's outcome (or, on failure, its original error) with an I/O error.
      this.opts.log?.(`run record could NOT be written: ${String(e?.message ?? e)}`);
      return record;
    }
  }
}

/**
 * Compact the page's body text into a short, single-line summary for a failed record.
 * Returns null when the page is gone, wedged, or empty — the record is still written.
 */
export async function summarizePage(
  page: { evaluate: (expression: string) => Promise<any> } | null | undefined,
  maxChars = 600,
): Promise<string | null> {
  if (!page) return null;
  try {
    const raw = await page.evaluate("document.body ? document.body.innerText : ''");
    const compact = String(raw ?? "").replace(/\s+/g, " ").trim();
    if (!compact) return null;
    return compact.length > maxChars ? compact.slice(0, maxChars) + "…" : compact;
  } catch {
    return null;
  }
}
