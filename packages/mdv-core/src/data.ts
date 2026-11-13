import fs from "node:fs/promises";
import path from "node:path";

export type Row = Record<string, string | number | boolean | null>;

export interface CsvParseResult {
  rows: Row[];
  warnings: string[];
}

/**
 * A remote dataset source declared in front-matter:
 *
 * ```yaml
 * data:
 *   sales:
 *     url: https://example.com/sales.csv
 *     format: csv
 *     headers: { Authorization: "Bearer …" }
 *     timeoutMs: 5000
 * ```
 */
export interface RemoteDatasetSource {
  url: string;
  /** Response body format. Inferred from a `.json` URL path when omitted; otherwise CSV. */
  format?: "csv" | "json";
  /** Extra request headers, sent verbatim. */
  headers?: Record<string, string>;
  /** Per-request timeout in milliseconds (default 10s, capped at 2 min). */
  timeoutMs?: number;
}

/** One entry of a dataset declaration: a local relative path or a remote source. */
export type DatasetSourceEntry = string | RemoteDatasetSource;

/** A dataset declaration value: one source, or an ordered list merged row-by-row. */
export type DatasetSource = DatasetSourceEntry | DatasetSourceEntry[];

export interface LoadedDataset {
  rows: Row[];
  warnings: string[];
}

/** Default per-request timeout for remote sources. */
export const DEFAULT_REMOTE_TIMEOUT_MS = 10_000;
/** Hard upper bound applied to a declared `timeoutMs`, so a document cannot hang a render. */
export const MAX_REMOTE_TIMEOUT_MS = 120_000;
/** Refuse responses larger than this; chart data should never be this big. */
const MAX_REMOTE_BYTES = 25 * 1024 * 1024;

function coerce(v: string): string | number | boolean | null {
  const t = v.trim();
  if (t === "") return "";
  if (t === "true") return true;
  if (t === "false") return false;
  if (t === "null") return null;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}

export function parseCsvFull(src: string, delimiter = ","): CsvParseResult {
  const lines: string[][] = [];
  let cur: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (inQuotes) {
      if (c === '"' && src[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') inQuotes = false;
      else field += c;
    } else {
      if (c === '"') inQuotes = true;
      else if (c === delimiter) { cur.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && src[i + 1] === "\n") i++;
        cur.push(field); field = "";
        if (cur.some(f => f !== "")) lines.push(cur);
        cur = [];
      } else field += c;
    }
  }
  if (field !== "" || cur.length) {
    cur.push(field);
    if (cur.some(f => f !== "")) lines.push(cur);
  }
  if (lines.length === 0) return { rows: [], warnings: [] };
  const header = lines[0].map(h => h.trim());
  const warnings: string[] = [];
  const MAX_RAGGED_WARNINGS = 3;
  const delimName = delimiter === "\t" ? "tab" : delimiter === "," ? "comma" : `'${delimiter}'`;
  const quoted = delimiter === "\t" ? '"a\tb"' : '"1,238"';
  let ragged = 0;
  const rows = lines.slice(1).map((row, idx) => {
    // A trailing delimiter produces one extra empty field; that is harmless and
    // renders identically, so only warn when the surplus/deficit is meaningful.
    const surplusAllEmpty = row.length > header.length && row.slice(header.length).every((f) => f === "");
    if (row.length !== header.length && !surplusAllEmpty) {
      ragged++;
      if (ragged <= MAX_RAGGED_WARNINGS) {
        warnings.push(
          `Data row ${idx + 1} has ${row.length} fields but the header has ${header.length} columns — ` +
          `quote values that contain the ${delimName} (e.g. ${quoted})`,
        );
      }
    }
    const r: Row = {};
    header.forEach((h, i) => {
      const raw = row[i] ?? "";
      r[h] = coerce(raw);
    });
    return r;
  });
  if (ragged > MAX_RAGGED_WARNINGS) {
    warnings.push(`…and ${ragged - MAX_RAGGED_WARNINGS} more rows with mismatched field counts`);
  }
  return { rows, warnings };
}

export function parseCsv(src: string, delimiter = ","): Row[] {
  return parseCsvFull(src, delimiter).rows;
}

export function parseJson(src: string): Row[] {
  const v = JSON.parse(src);
  if (!Array.isArray(v)) throw new Error("JSON data must be an array of objects");
  for (const item of v) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      throw new Error("JSON data must be an array of objects (found a non-object element)");
    }
  }
  return v as Row[];
}

export async function loadDataset(relPath: string, baseDir: string, warnings?: string[]): Promise<Row[]> {
  const normalizedBase = path.resolve(baseDir);
  const full = path.resolve(normalizedBase, relPath);
  const rel = path.relative(normalizedBase, full);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`Data file path escapes base directory: ${relPath}`);
  }
  let src: string;
  try {
    src = await fs.readFile(full, "utf8");
  } catch (e) {
    // Report the author's relative reference, not the absolute path — error
    // messages end up in shareable rendered HTML.
    const code = (e as NodeJS.ErrnoException).code;
    if (code === "ENOENT") throw new Error(`Data file not found: ${relPath}`);
    throw new Error(`Cannot read data file '${relPath}'${code ? ` (${code})` : ""}`);
  }
  const ext = path.extname(full).toLowerCase();
  if (ext === ".csv" || ext === ".tsv") {
    const res = parseCsvFull(src, ext === ".tsv" ? "\t" : ",");
    if (warnings) warnings.push(...res.warnings);
    return res.rows;
  }
  if (ext === ".json") return parseJson(src);
  throw new Error(`Unsupported data file extension: ${ext}`);
}

// --- Multi-source datasets ---------------------------------------------------

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function sourceLabel(entry: unknown): string {
  if (typeof entry === "string") return entry;
  if (entry && typeof entry === "object" && !Array.isArray(entry)) {
    const url = (entry as { url?: unknown }).url;
    if (typeof url === "string" && url.trim() !== "") return redactUrl(url.trim());
  }
  return "(missing url)";
}

/**
 * Strip embedded credentials before a URL is echoed into a warning. Rendered
 * HTML is often shared, so `https://user:token@host/…` must not leak the token.
 */
function redactUrl(raw: string): string {
  try {
    const url = new URL(raw);
    if (url.username || url.password) {
      url.username = "";
      url.password = "";
      return url.toString();
    }
    return raw;
  } catch {
    return raw;
  }
}

/**
 * Load one declared source. A bare string keeps the historical local-file
 * semantics; an object is fetched over http/https.
 */
async function loadOneSource(entry: unknown, baseDir: string): Promise<LoadedDataset> {
  if (typeof entry === "string") {
    const warnings: string[] = [];
    const rows = await loadDataset(entry, baseDir, warnings);
    return { rows, warnings };
  }
  if (entry && typeof entry === "object" && !Array.isArray(entry)) {
    return loadRemoteSource(entry as RemoteDatasetSource);
  }
  throw new Error("a dataset source must be a local path string or an object with a 'url'");
}

function resolveRemoteFormat(format: unknown, url: URL): "csv" | "json" {
  if (format === undefined) {
    // Without an explicit format, a `.json` URL path is the only reliable hint;
    // everything else is treated as CSV, matching the inline default.
    return path.extname(url.pathname).toLowerCase() === ".json" ? "json" : "csv";
  }
  const normalized = typeof format === "string" ? format.trim().toLowerCase() : format;
  if (normalized === "csv" || normalized === "json") return normalized;
  throw new Error(`invalid format ${JSON.stringify(format)} (expected "csv" or "json")`);
}

function parseRemoteBody(text: string, format: "csv" | "json"): LoadedDataset {
  if (format === "json") {
    try {
      return { rows: parseJson(text), warnings: [] };
    } catch (e) {
      throw new Error(`parse failed: ${errText(e)}`);
    }
  }
  // CSV parsing never throws; ragged-row diagnostics are preserved and surface
  // through the same warning path as local files.
  const res = parseCsvFull(text);
  return { rows: res.rows, warnings: res.warnings };
}

function networkErrorDetail(e: unknown): string {
  const err = e as { message?: string; cause?: { code?: string } };
  const base = err?.message || String(e);
  return err?.cause?.code ? `${base} (${err.cause.code})` : base;
}

/** Fetch and parse one remote source. Throws a human-readable reason on any failure. */
async function loadRemoteSource(source: RemoteDatasetSource): Promise<LoadedDataset> {
  if (typeof source.url !== "string" || source.url.trim() === "") {
    throw new Error("remote dataset source requires a non-empty 'url'");
  }
  const rawUrl = source.url.trim();
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`invalid URL '${redactUrl(rawUrl)}'`);
  }
  // Security: only web protocols. file:, data:, and anything else are refused
  // before a request is attempted, and count as a failed source.
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`unsupported URL protocol '${url.protocol}' (only http and https are allowed)`);
  }

  const format = resolveRemoteFormat(source.format, url);

  const headers: Record<string, string> = {};
  if (source.headers !== undefined) {
    if (source.headers === null || typeof source.headers !== "object" || Array.isArray(source.headers)) {
      throw new Error("invalid 'headers' (expected a mapping of header names to string values)");
    }
    for (const [key, value] of Object.entries(source.headers)) {
      if (value !== null && typeof value === "object") {
        throw new Error(`invalid header '${key}' (header values must be strings)`);
      }
      const text = String(value);
      // Header injection guard: CR/LF would let front-matter inject extra
      // headers (or a whole second request) into the outgoing request.
      if (/[\r\n]/.test(key) || /[\r\n]/.test(text)) {
        throw new Error(`invalid header '${key}' (must not contain line breaks)`);
      }
      headers[key] = text;
    }
  }

  let timeoutMs = DEFAULT_REMOTE_TIMEOUT_MS;
  if (source.timeoutMs !== undefined) {
    const t = source.timeoutMs;
    if (typeof t !== "number" || !Number.isFinite(t) || t <= 0) {
      throw new Error(`invalid 'timeoutMs' ${JSON.stringify(t)} (expected a positive number)`);
    }
    timeoutMs = Math.min(t, MAX_REMOTE_TIMEOUT_MS);
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    let res: Response;
    try {
      res = await fetch(rawUrl, { headers, signal: controller.signal, redirect: "follow" });
    } catch (e) {
      if (timedOut) throw new Error(`timeout after ${timeoutMs} ms (no response)`);
      throw new Error(`request failed: ${networkErrorDetail(e)}`);
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`);
    }
    const declared = Number(res.headers.get("content-length"));
    if (Number.isFinite(declared) && declared > MAX_REMOTE_BYTES) {
      throw new Error(`response too large (${declared} bytes)`);
    }
    let text: string;
    try {
      text = await res.text();
    } catch (e) {
      if (timedOut) throw new Error(`timeout after ${timeoutMs} ms while reading the response`);
      throw new Error(`request failed while reading the response: ${networkErrorDetail(e)}`);
    }
    if (text.length > MAX_REMOTE_BYTES) throw new Error(`response too large (${text.length} bytes)`);
    return parseRemoteBody(text, format);
  } finally {
    clearTimeout(timer);
  }
}

/** Human-readable failure line for one source, naming the source and the reason. */
function describeSourceFailure(entry: unknown, e: unknown): string {
  const label = sourceLabel(entry);
  return `Data source '${label}' failed: ${errText(e)}`;
}

/**
 * Resolve a front-matter dataset declaration.
 *
 * - A bare string keeps the existing local-file behaviour exactly (including
 *   its error messages and path-escape guard).
 * - An object is a remote source fetched over http/https.
 * - An array merges the rows of every entry, in declaration order. A failing
 *   entry contributes a warning (not a blank block) as long as at least one
 *   other entry succeeded. When every entry fails, the error is rethrown so
 *   the block renders its usual block-level banner.
 */
export async function loadDatasetDeclaration(
  declaration: unknown,
  baseDir: string,
  name: string,
  warnings: string[],
): Promise<Row[]> {
  // Preserve the original single-local-path contract byte for byte.
  if (typeof declaration === "string") {
    return loadDataset(declaration, baseDir, warnings);
  }

  const entries: unknown[] = Array.isArray(declaration) ? declaration : [declaration];
  if (entries.length === 0) {
    throw new Error(`Dataset '${name}' declares an empty list of sources`);
  }

  // Fetch every source concurrently so N slow/timed-out sources do not stack
  // their timeouts serially. Promise.allSettled keeps results in declaration
  // order, so merged rows and warnings stay deterministic.
  const results = await Promise.allSettled(entries.map((entry) => loadOneSource(entry, baseDir)));

  const rows: Row[] = [];
  const failures: string[] = [];
  results.forEach((result, i) => {
    if (result.status === "fulfilled") {
      rows.push(...result.value.rows);
      warnings.push(...result.value.warnings);
    } else {
      failures.push(describeSourceFailure(entries[i], result.reason));
    }
  });

  if (failures.length === entries.length) {
    // Every source failed: use the existing block-level error path.
    if (failures.length === 1) throw new Error(failures[0]);
    throw new Error(
      `All ${failures.length} sources for dataset '${name}' failed:\n` + failures.join("\n"),
    );
  }

  warnings.push(...failures);
  return rows;
}
