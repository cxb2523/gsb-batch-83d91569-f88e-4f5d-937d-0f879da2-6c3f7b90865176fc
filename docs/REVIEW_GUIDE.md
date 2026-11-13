# Technical Review Guide

This guide is for someone evaluating the project from GitHub without reading every file. It follows the main user journeys through the same seams used by the application.

## Five-minute tour

1. Read the root [`README.md`](../README.md) for the product, architecture, scope, and validation status.
2. Read [`CODEBASE_MAP.md`](CODEBASE_MAP.md) for ownership and dependency direction.
3. Open [`apps/desktop/src/main.ts`](../apps/desktop/src/main.ts) to see the Electron shell and native-process responsibilities.
4. Open [`apps/backend/src/server.ts`](../apps/backend/src/server.ts) to see the backend composition root and stable error handling.
5. Open [`apps/frontend/src/useAppWorkflow.ts`](../apps/frontend/src/useAppWorkflow.ts) and [`apps/frontend/src/App.tsx`](../apps/frontend/src/App.tsx) to see renderer orchestration and view selection.
6. Run `npm install`, `npm test`, and `npm run build`.

## Follow the important workflows

### Upcoming-release sync

Start at [`apps/backend/src/routes/syncRoutes.ts`](../apps/backend/src/routes/syncRoutes.ts), then follow:

```text
syncRoutes
  → syncRun
  → igdbCandidateSource / igdb client
  → rules and releaseSyncPlanner
  → releaseMerge
  → releaseStore (Release Store)
```

This is the main data pipeline. Normalization, eligibility, merge decisions, blocking, and artwork enrichment are kept in backend modules rather than in the route or renderer.

### Completed Library

Start at [`apps/backend/src/routes/completedRoutes.ts`](../apps/backend/src/routes/completedRoutes.ts), then follow:

```text
completedRoutes → completedActions (runWrite) → completedGameStore
completedReadModel → list/detail
```

Identity is based on normalized title plus user platform, and manual match overrides survive later edits.

### Renderer state and interaction

The renderer follows this direction:

```text
App.tsx
  → useAppWorkflow
  → feature workflow modules
  → api/client.ts
  → backend HTTP routes
  → views render returned state
```

Views emit intent; workflow modules own state transitions and side effects; the API client owns transport details.

### Runtime and recovery

Inspect [`apps/runtime/src/layout.ts`](../apps/runtime/src/layout.ts) for app-data and restore discovery, [`apps/backend/src/diagnostics/logger.ts`](../apps/backend/src/diagnostics/logger.ts) for redacted logging, and [`apps/frontend/src/ErrorBoundary.tsx`](../apps/frontend/src/ErrorBoundary.tsx) for renderer recovery.

## What the tests demonstrate

- `tests/backend/` exercises database migrations, stores, read models, routes, sync rules, provider adapters, diagnostics, and runtime layout.
- `tests/desktop/` exercises lifecycle, native IPC, and desktop-facing storage.
- `tests/frontend/` exercises the application shell, workflows, API error behaviour, selection, wallpaper, error recovery, and renderer contracts.

Tests are deliberately close to the module seams. A reviewer can use a failing test to locate the owning interface instead of tracing through the whole process graph.

## Design decisions worth discussing

- **Separate backend child:** keeps database and provider credentials out of the renderer and gives desktop lifecycle code a clear process to supervise.
- **Read models:** keep list payloads light and reserve screenshots, trailers, and rich metadata for detail views.
- **Sync planning and merge rules:** make external data changes inspectable and prevent a sync from blindly overwriting user decisions.
- **App-data ownership:** keeps wallpapers, databases, and logs outside the renderer and outside the source repository.
- **Stable error responses plus diagnostics:** the UI receives safe messages while the local log retains redacted diagnostic detail.

## Known tradeoffs

- The project is intentionally single-user and local-first; it has no authentication or hosted API.
- The desktop packaging path is Windows-focused even though the source can be developed and tested on Linux.
- IGDB and optional SteamGridDB features are network- and credential-dependent.
- The repository has a detailed architecture map because the application has more behaviour than a small demo; the map is the entry point for future contributors.
