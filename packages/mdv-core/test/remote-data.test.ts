import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "../src/parser.ts";
import { renderDocument } from "../src/render/html.ts";

const here = path.dirname(fileURLToPath(import.meta.url));

let server: http.Server;
let base: string;

// Each route exercises one failure mode so warning messages can be told apart.
before(async () => {
  server = http.createServer((req, res) => {
    const route = (req.url || "/").split("?")[0];
    const send = (status: number, body: string, type = "text/csv") => {
      res.writeHead(status, { "Content-Type": type });
      res.end(body);
    };
    if (route === "/ok.csv") return send(200, "region,sales\nNorth,120\nSouth,95\n");
    if (route === "/ok2.csv") return send(200, "region,sales\nEast,70\n");
    if (route === "/ok.json") return send(200, '[{"region":"West","sales":140}]', "application/json");
    if (route === "/bad-json") return send(200, '{"not":"an array"}', "application/json");
    if (route === "/ragged.csv") return send(200, "region,sales\nNorth,120,extra\n");
    if (route === "/500") return send(500, "boom");
    if (route === "/404") return send(404, "not found");
    if (route === "/headers") {
      // Echo whether the declared header arrived, as CSV data.
      const seen = req.headers["x-mdv-test"] === "yes" ? "yes" : "no";
      return send(200, `seen\n${seen}\n`);
    }
    if (route === "/hang") return; // never responds — exercises the timeout
    send(404, "unknown route");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const addr = server.address() as { port: number };
  base = `http://127.0.0.1:${addr.port}`;
});

after(async () => {
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function frontmatter(yaml: string): string {
  return `---\n${yaml}\n---\n`;
}

async function renderSource(src: string): Promise<{ html: string; doc: Awaited<ReturnType<typeof parse>> }> {
  const doc = await parse(src, { baseDir: here });
  return { html: renderDocument(doc), doc };
}

// --- Mixed success / failure ---------------------------------------------------

test("mixed sources: chart still draws and each failed source gets its own warning", async () => {
  const src =
    frontmatter(
      [
        "data:",
        "  sales:",
        "    - url: " + JSON.stringify(`${base}/ok.csv`),
        "    - url: " + JSON.stringify(`${base}/500`),
        "    - url: " + JSON.stringify(`${base}/404`),
        "    - url: " + JSON.stringify(`${base}/bad-json`),
        "      format: json",
      ].join("\n"),
    ) +
    "```chart type=bar x=region y=sales data=sales\n```\n";

  const { html, doc } = await renderSource(src);

  // Successful rows still reach the chart, so a bar is drawn.
  assert.match(html, /<rect/);
  assert.doesNotMatch(html, /<div class="mdv-error"/, "a partial failure must not blank the block");

  const warnings = doc.tokens
    .filter((t) => t.kind === "error" && t.meta.severity === "warning")
    .map((t) => (t.kind === "error" ? t.meta.message : ""));
  assert.equal(warnings.length, 3, "one warning per failed source");

  // Each warning names the source and its distinguishable reason.
  assert.ok(warnings.some((w) => w.includes(`${base}/500`) && /HTTP 500/.test(w)), "HTTP failure named");
  assert.ok(warnings.some((w) => w.includes(`${base}/404`) && /HTTP 404/.test(w)), "HTTP 404 named");
  assert.ok(warnings.some((w) => w.includes(`${base}/bad-json`) && /parse failed/.test(w)), "parse failure named");
});

test("warning banner for a failed source appears in rendered HTML alongside the chart", async () => {
  const src =
    frontmatter(
      `data:\n  sales:\n    - url: ${JSON.stringify(`${base}/ok2.csv`)}\n    - url: ${JSON.stringify(`${base}/500`)}`,
    ) +
    "```chart type=bar x=region y=sales data=sales\n```\n";
  const { html } = await renderSource(src);
  assert.match(html, /class="mdv-warning"/);
  assert.match(html, new RegExp(`${base}/500`.replace(/[.]/g, ".")));
  assert.match(html, /HTTP 500/);
  assert.match(html, /<rect/);
});

// --- Timeout -------------------------------------------------------------------

test("a hanging source is reported as a timeout, distinct from HTTP and parse failures", async () => {
  const src =
    frontmatter(
      [
        "data:",
        "  sales:",
        "    - url: " + JSON.stringify(`${base}/ok.csv`),
        "    - url: " + JSON.stringify(`${base}/hang`),
        "      timeoutMs: 50",
      ].join("\n"),
    ) +
    "```table data=sales\n```\n";

  const { html, doc } = await renderSource(src);
  assert.doesNotMatch(html, /<div class="mdv-error"/);
  assert.match(html, /<table/);

  const warnings = doc.tokens
    .filter((t) => t.kind === "error" && t.meta.severity === "warning")
    .map((t) => (t.kind === "error" ? t.meta.message : ""));
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /timeout/i);
  assert.ok(warnings[0].includes(`${base}/hang`), "warning names the source");
});

// --- Protocol safety -------------------------------------------------------------

test("non-http(s) URL protocols are rejected without a request and count as failures", async () => {
  const src =
    frontmatter(
      [
        "data:",
        "  sales:",
        "    - url: " + JSON.stringify(`${base}/ok.csv`),
        "    - url: file:///etc/passwd",
        "    - url: data:text/csv,a,b",
      ].join("\n"),
    ) +
    "```table data=sales\n```\n";

  const { html, doc } = await renderSource(src);
  assert.match(html, /<table/);
  const warnings = doc.tokens
    .filter((t) => t.kind === "error" && t.meta.severity === "warning")
    .map((t) => (t.kind === "error" ? t.meta.message : ""));
  assert.equal(warnings.length, 2);
  assert.ok(warnings.some((w) => w.includes("file:///etc/passwd") && /protocol/.test(w)));
  assert.ok(warnings.some((w) => w.startsWith("Data source 'data:text/csv") && /protocol/.test(w)));
});

test("a document whose only source is a bad protocol renders the usual block-level error", async () => {
  const src =
    frontmatter(`data:\n  sales:\n    - url: ftp://example.com/sales.csv`) +
    "```chart type=bar x=region y=sales data=sales\n```\n";
  const { html, doc } = await renderSource(src);
  assert.match(html, /<div class="mdv-error"/);
  assert.match(html, /protocol/);
  assert.ok(!doc.tokens.some((t) => t.kind === "chart"), "no chart token when every source fails");
});

// --- Success paths ---------------------------------------------------------------

test("remote JSON is parsed when format: json is declared", async () => {
  const src =
    frontmatter(`data:\n  sales: { url: ${JSON.stringify(`${base}/ok.json`)}, format: json }`) +
    "```table data=sales\n```\n";
  const { html, doc } = await renderSource(src);
  assert.match(html, /<td>West<\/td>/);
  assert.match(html, /<td>140<\/td>/);
  assert.ok(!doc.tokens.some((t) => t.kind === "error"));
});

test("declared headers are sent with the request", async () => {
  const src =
    frontmatter(
      `data:\n  sales:\n    url: ${JSON.stringify(`${base}/headers`)}\n    headers:\n      X-MDV-Test: yes`,
    ) + "```table data=sales\n```\n";
  const { html } = await renderSource(src);
  assert.match(html, /<td>yes<\/td>/);
});

test("a single remote object (no array) is accepted and rows are merged in declaration order", async () => {
  const src =
    frontmatter(
      [
        "data:",
        "  sales:",
        "    - url: " + JSON.stringify(`${base}/ok.csv`),
        "    - url: " + JSON.stringify(`${base}/ok2.csv`),
      ].join("\n"),
    ) +
    "```table data=sales\n```\n";
  const { doc } = await renderSource(src);
  const table = doc.tokens.find((t) => t.kind === "table");
  assert.ok(table && table.kind === "table");
  if (table && table.kind === "table") {
    assert.equal(table.meta.data.length, 3, "rows from both sources concatenated");
    assert.deepEqual(
      table.meta.data.map((r) => r.region),
      ["North", "South", "East"],
      "declaration order preserved",
    );
  }
});

test("remote CSV still produces the existing ragged-row warning", async () => {
  const src =
    frontmatter(`data:\n  sales:\n    url: ${JSON.stringify(`${base}/ragged.csv`)}`) +
    "```table data=sales\n```\n";
  const { doc, html } = await renderSource(src);
  const warnings = doc.tokens.filter((t) => t.kind === "error" && t.meta.severity === "warning");
  assert.equal(warnings.length, 1);
  assert.match(html, /fields but the header has/);
  assert.match(html, /<table/);
});

// --- Backwards compatibility -----------------------------------------------------

test("a plain local string dataset keeps its existing behaviour and messages", async () => {
  const src =
    frontmatter("data:\n  sales: ./fixtures/sales.csv") +
    "```chart type=bar x=region y=sales data=sales\n```\n";
  const { html, doc } = await renderSource(src);
  assert.match(html, /<rect/);
  assert.ok(!doc.tokens.some((t) => t.kind === "error"));
});

test("an array of local path strings merges rows in declaration order", async () => {
  const src =
    frontmatter("data:\n  sales:\n    - ./fixtures/sales.csv\n    - ./fixtures/sales.tsv") +
    "```table data=sales\n```\n";
  const { doc } = await renderSource(src);
  const table = doc.tokens.find((t) => t.kind === "table");
  assert.ok(table && table.kind === "table");
  if (table && table.kind === "table") {
    assert.equal(table.meta.data.length, 8, "both local files contribute rows");
    assert.equal(table.meta.data[0].region, "North");
    assert.equal(table.meta.data[4].region, "North", "second file's rows follow the first's");
  }
});

test("mixed local and remote sources merge in declaration order", async () => {
  const src =
    frontmatter(
      [
        "data:",
        "  sales:",
        "    - ./fixtures/sales.csv",
        "    - url: " + JSON.stringify(`${base}/ok2.csv`),
      ].join("\n"),
    ) +
    "```table data=sales\n```\n";
  const { doc } = await renderSource(src);
  const table = doc.tokens.find((t) => t.kind === "table");
  assert.ok(table && table.kind === "table");
  if (table && table.kind === "table") {
    assert.deepEqual(
      table.meta.data.map((r) => r.region),
      ["North", "South", "East", "West", "East"],
    );
  }
});


test("a missing local string dataset still renders the original missing-file banner", async () => {
  const src =
    frontmatter("data:\n  sales: ./fixtures/nope.csv") +
    "```chart type=bar x=region y=sales data=sales\n```\n";
  const { html } = await renderSource(src);
  assert.match(html, /mdv-error/);
  assert.match(html, /Data file not found: \.\/fixtures\/nope\.csv/);
  assert.ok(!html.includes(here), "must not leak the absolute path");
});
