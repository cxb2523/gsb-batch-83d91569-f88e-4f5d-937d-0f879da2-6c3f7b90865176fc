# Examples

TypeScript scripts that show how to use each namespace in the Olostep Node SDK.

## Prerequisites

1. Install dependencies at the project root: `npm install`.
2. Export your API key: `export OLOSTEP_API_KEY="..."` (PowerShell: `$env:OLOSTEP_API_KEY="..."`).
3. Run the scripts with a TS runner such as [`tsx`](https://github.com/esbuild-kit/tsx) or `ts-node` (add to `devDependencies` if needed).
4. Optional environment overrides supported by the helper:
   - `OLOSTEP_BASE_API_URL` – use a custom API base (default `https://api.olostep.com/v1`).
   - `OLOSTEP_API_TIMEOUT` – request timeout in seconds (default `150`).

## Running

```bash
npx tsx examples/scrape.ts
npx tsx examples/batch.ts
npx tsx examples/crawl.ts
npx tsx examples/map.ts
npx tsx examples/retrieve.ts <retrieve_id>
```

Each script logs the handle returned by the SDK and some representative follow-up calls:

- `scrape.ts` prints the immediate scrape summary and, if a `retrieve_id` is available, calls `client.retrieve()` to fetch fresh content.
- `batch.ts`, `crawl.ts`, and `map.ts` currently log basic metadata; streaming iterators / wait helpers will be wired up once those APIs land in the SDK.

Use these scripts as a starting point for manual smoke tests or for reproducing API issues.

