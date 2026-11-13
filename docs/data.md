# Data

Every visualization block needs data. You have three options, in order of simplicity.
## 1. Inline CSV (default)

The fence body is a CSV with a header row.

````
```chart type=bar x=region y=sales
region, sales
North, 120
South, 95
```
````

**Parsing:**
- Comma-separated. Whitespace around values is trimmed.
- Quoted fields handle commas and embedded quotes: `"Smith, J."`, `"He said ""hi"""`.
- Types auto-detected per cell: numbers → `number`, `true`/`false`/`null` → their literals, everything else → `string`.
- No type declarations are needed or supported.

## 2. Inline JSON

Opt in with `format=json`. The body must be a JSON array of objects.

````
```chart type=pie label=name value=share format=json
[
  {"name": "Alpha", "share": 45},
  {"name": "Beta",  "share": 30}
]
```
````

Use JSON when your data is already structured that way (e.g. pasted from an API response you've pre-aggregated). CSV is more convenient for most typing-by-hand cases.

## 3. Named datasets (file and remote references)

Declare once in front-matter, reuse everywhere.

```yaml
---
data:
  sales: ./data/sales.csv
  regions: ./data/regions.json
  q1: ./data/q1.tsv
---
```

Then reference by name:

````
```chart type=line data=sales x=month y=revenue series=region
```

```table data=sales
```
````

A named dataset may be declared in three ways:

1. **A local path string** — the behaviour described below (unchanged).
2. **A remote source object** — fetched over HTTP(S) at render time:
   ```yaml
   data:
     sales:
       url: https://example.com/api/sales.csv
       format: csv            # csv (default) | json
       headers:               # optional, sent with the request
         Authorization: "Bearer …"
       timeoutMs: 5000        # optional, default 10000, capped at 120000
   ```
3. **An array of entries** — each entry is a local path string or a remote
   source object. The rows of every source are concatenated **in declaration
   order**:
   ```yaml
   data:
     sales:
       - ./data/sales-2025.csv
       - url: https://example.com/api/sales-2026.csv
       - url: https://example.com/api/sales-archive.json
         format: json
   ```

**File resolution rules (local paths):**
- Paths are **always relative to the `.mdv` file**.
- Absolute local paths are **not supported**, and a path that escapes the
  document directory is rejected — a hard line to keep docs portable.
- Supported extensions: `.csv`, `.tsv` (parsed like CSV), `.json`.
- Missing or unreadable files render an inline **error banner** but the rest of the document continues.

**Remote source rules:**
- Only `http:` and `https:` URLs are allowed. Any other protocol (`file:`,
  `data:`, `ftp:`, …) is rejected before a request is made and counts as a
  failed source.
- `format=json` (or a `.json` URL path) parses the body as a JSON array of
  objects. Otherwise the body is parsed as CSV, including the usual ragged-row
  warnings.
- `timeoutMs` bounds each request. When omitted it defaults to 10 seconds; the
  declared value is capped at 2 minutes.
- Fetching uses Node's built-in `fetch` — there is no runtime dependency, and
  the request never happens in the browser/PDF viewer.

**Partial failures in a multi-source dataset:**
- A source that fails (timeout, non-2xx HTTP status, network error, parse
  error, or a disallowed protocol) does **not** blank the block. Its rows are
  simply absent, and a **yellow warning** names the source (its URL or path)
  and the reason — so a timeout, an `HTTP 500`, and a `parse failed` are
  distinguishable at a glance.
- Each failed source gets its own warning; successful sources still render.
- **Only when every source fails** does the block fall back to its usual
  block-level red error banner.

## Error cases

| Situation | What happens |
|---|---|
| Unknown `data=` name | Block renders as a red error banner; other blocks still render. |
| Missing file | Block renders as a red error banner naming the path. |
| Malformed CSV | Block renders as a red error banner. |
| Empty dataset | Block renders as a red "no data rows" banner. |
| Column referenced by `x=`/`y=` that doesn't exist | Treated as `undefined` → numerical cells become `NaN`; usually visible as blank bars/flat lines. |
| One of several sources fails | A yellow warning per failed source; the block renders using the rows that succeeded. |
| Every source fails | Block renders as a red error banner listing each failure. |

## What's not supported

MDV is deliberately small. These are **not** data features:

- **No transformations.** No filter, group-by, aggregate, compute, or sort. Pre-aggregate your data.
- **No non-HTTP data access.** Remote sources must be `http(s)`. No database
  drivers, no `file:` URLs, no local sockets.
- **No auth flows.** Static `headers:` are supported; OAuth/interactive login
  is not.
- **No queries.** You can't say `data=sales where region=North`. That's code, which MDV explicitly avoids.
- **No parametrization.** No `{{ }}` templating of info strings with data values.

If you find yourself wanting these, pre-process the data in your tool of choice and save the result as a new CSV/JSON.
