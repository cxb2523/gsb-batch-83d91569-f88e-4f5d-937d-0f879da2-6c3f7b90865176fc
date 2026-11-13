# Backend

The backend is a Fastify child process. `src/server.ts` composes the HTTP server and route modules; `src/child.ts` starts the process and reports its port and fatal failures.

## Module ownership

- `routes/` — HTTP transport and response mapping.
- `actions/` — multi-step user workflows.
- `database/` — SQLite migrations, stores, repositories, read models, and write serialization.
- `completed/` — completed-library domain logic.
- `sync/` — upcoming-release normalization, planning, merging, and enrichment.
- `igdb/`, `steamgriddb/` — external provider adapters.
- `artwork/`, `settings/`, `diagnostics/`, `matching/` — focused supporting modules.

Routes should delegate behaviour to deeper modules rather than containing SQL, provider orchestration, or filesystem code. See [`docs/CODEBASE_MAP.md`](../../docs/CODEBASE_MAP.md).
