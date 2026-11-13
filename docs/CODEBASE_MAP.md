# Codebase Map

This is the navigation guide for the Game Release Tracker codebase. It explains ownership and change seams; the build scripts and TypeScript/Vite configuration remain the source of truth for commands and compilation.

## Repository shape

```text
.
├── apps/
│   ├── backend/       Fastify child process and application modules
│   ├── desktop/       Electron main process and native IPC adapters
│   ├── frontend/      React renderer, workflows, API client, and views
│   └── runtime/       App-data paths and filesystem storage
├── shared/            Types and constants shared across process seams
├── tests/
│   ├── backend/       Backend, persistence, sync, and route tests
│   ├── desktop/       Electron lifecycle and IPC tests
│   └── frontend/      Renderer, workflow, and view tests
├── docs/              Product, architecture, beginner, and planning docs
│   └── adr/           Decision records: why the app is shaped the way it is
├── scripts/           Build helpers (bundle, afterPack) and the packaged smoke test
├── build/             Packaging assets such as application icons
├── dist/              Generated TypeScript/Vite/package output; never source
├── node_modules/      Installed dependencies; never source
└── game-release-tracker/
    Local Electron restore data: database, wallpaper, logs, and caches.
    It is personal runtime data, not application source, and is excluded locally.
```

The restore directory is intentionally separate from the source modules. New packages carry no personal data. To restore a backup, set `GRT_RESTORE_DIR` to its directory; development also discovers the `game-release-tracker/` backup beside the repository root.

## Process and dependency direction

```text
Electron main (apps/desktop)
        │ starts and supervises
        ▼
Fastify backend child (apps/backend) ───────► runtime file storage (apps/runtime)
        │                                             │
        ├── SQLite stores/read models                 └── app-data paths/files
        ├── sync and provider adapters
        └── REST routes

React renderer (apps/frontend) ──HTTP──► Fastify routes
        │
        └──────────────────────────────► shared types/constants

Backend, desktop, and frontend may consume shared types/constants.
The shared folder must not import application-specific modules.
```

The backend is the composition root for HTTP routes and domain modules. The Electron process owns native capabilities. The renderer owns presentation state and user intent. Runtime modules own app-data files. Keeping those interfaces stable lets the implementation change locally without forcing every caller to learn the internals.

## Folder ownership

### `apps/backend/src`

The Fastify child process and the server-side application modules.

- `child.ts` — backend-process bootstrap, runtime layout, startup reporting, and fatal-process handling.
- `server.ts` — composition root: creates Fastify, installs request/error handling, and registers routes.
- `routes/` — HTTP transport only. Parse requests, call an action/store/workflow, and return a stable response.
- `actions/` — multi-step user workflows such as manual release changes, deletion/blocking, completed-game operations, and Randomizer spins.
- `database/` — SQLite connection, migrations, stores, read models, and write serialization. `releaseStore.ts` is the Release Store: the only module that writes release tables (media, sources, search index, overrides, blocks, seeds, eligibility). Sync and actions ask it questions (`exists`, `isBlocked`, `idForIgdbGame`, `loadMergeState`) instead of running release SQL themselves.
- `completed/` — completed-library domain: identity, matching, metadata, personal fields and ratings, and stores.
- `randomizer/` — IGDB Randomizer: filter validation and query text (`queryBuilder.ts`), the pure draw and cooldown shrink (`draw.ts`, IGDB I/O injected), and pick history (`pickHistoryStore.ts`). It never writes release or completed-library tables.
- `yearInReview/` — Year in Review: the pure yearly recap (`buildYearInReview.ts`, the only interface of the recap logic; its tests go through it), every tunable number (`thresholds.ts`), and the per-year settings store (`yearInReviewSettingsStore.ts`, the only writer of `year_in_review_settings`). Completed games are read through `completedGameStore.yearInReviewRows`.
- `releaseAlerts/` — release alerts for watched games (`releaseAlerts.ts`): out today and recent date changes, each handed out once through `POST /api/alerts/take`; the only writer of `release_alerts_sent`. The desktop app turns them into notifications.
- `releaseDates/` — a release's date history (`dateChanges.ts`): the pure rule that names a change (delayed, announced, moved up), and the only reader/writer of `release_date_changes`. Sync records a change after saving a game; the read model attaches the newest to list items and all of them to the detail.
- `sync/` — upcoming-release sync planning, normalization, merge rules, IGDB candidate discovery, status, artwork enrichment, and the auto-sync schedule (`autoSyncSchedule.ts`: at startup, then every 30 minutes while running).
- `artwork/` — local artwork paths, release-artwork workflows, and the cover cache (`coverCache.ts`: IGDB covers downloaded once into `<app data>/covers/`, served at `/api/covers/:imageId`).
- `igdb/` and `steamgriddb/` — external provider adapters and credential/token handling. `igdb/gateway.ts` is the only IGDB entry point; tests pass a fake gateway to `createBackendApp({ igdb })`.
- `settings/` — `settingsStore.ts` is the only reader/writer of the `settings` table (credential key list, saved-over-environment fallback, seed version); `settingsCredentialModule.ts` reports safe credential status and tests credentials through the app's IGDB gateway. Library tables are read only through their stores (the Randomizer asks each store for `ownedIgdbIds`; admin routes use the Release Store; the sync log comes from `sync/syncStatus.ts`).
- `diagnostics/` — structured diagnostic logging and redaction.
- `matching/` — reusable title-matching logic that is not tied to an HTTP route.

### `apps/desktop/src`

The privileged Electron main process. It creates the window, starts/stops the backend child, owns lifecycle/crash handling, exposes the preload bridge, and implements native file-picker IPC for wallpapers, plus Year in Review's Save as image (`saveImageIpc.ts`). `startAtLogin.ts` registers the app to start at login in the tray (a Windows login item or a Linux autostart file). `releaseAlerts.ts` turns the backend's release alerts into system notifications. `trayWindow.ts` owns minimize to tray (the tray icon, its menu, and bringing the window back); `main.ts` only adapts Electron's `Tray` to it. In packaged mode it serves the renderer from the fixed `app://renderer` origin (`appProtocol.ts`), passing each request through to the backend.

### `apps/frontend/src`

The React renderer. `App.tsx` is the shell and view selection seam; `views/` renders screens; `api/` is the HTTP client; workflow modules own state transitions and side effects; media, selection, editing, grouping, wallpaper, and scroll-restoration modules keep cross-view behaviour out of individual screens.

### `apps/runtime/src`

Cross-process app-data storage. `layout.ts` resolves data directories and restore sources. The remaining modules own wallpaper and other filesystem operations. Runtime code should not contain React or route logic.

### `shared/`

The narrow cross-process contract: request/response types, domain payloads, enums, limits, constants, and the few pure rules both sides must agree on (`completedGenres`). Keep it dependency-light and free of filesystem, database, Electron, Fastify, or React imports.

### `tests/`

Tests mirror the runtime seams. Backend tests cover stores, read models, routes, sync, parsing, diagnostics, and database behavior. Desktop tests cover lifecycle and IPC. Frontend tests cover workflows, renderer behavior, and presentation contracts. Prefer testing through the same interface that production callers use.

### `docs/`

Human and agent-facing reference. `CONTEXT.md` is the domain vocabulary and decision record; `DOCUMENTATION.md` is the detailed technical reference; `USER_GUIDE.md` explains operation; `YEAR_IN_REVIEW_SPEC.md` is the implemented Year in Review's design record and planning notes describe future or scoped product work; this file is the source-folder map.

## Feature ownership map

| Feature | Backend seam | Frontend seam | Runtime/data seam |
|---|---|---|---|
| Upcoming releases | `routes/releaseRoutes.ts`, `actions/releaseActions.ts`, `database/` | `releaseWorkspace.ts`, release views | SQLite database |
| IGDB sync | `sync/`, `igdb/`, `routes/syncRoutes.ts` | `views/CollectionControls.tsx` (sync state), app workflows | SQLite sync tables and diagnostics |
| Completed library | `completed/`, `routes/completedRoutes.ts`, `actions/completedActions.ts` | completed workflows and views | — |
| Randomizer | `randomizer/`, `actions/randomizerActions.ts`, `routes/randomizerRoutes.ts`, `igdb/gateway.ts` (`count`, `multiquery`) | `useRandomizerWorkflow.ts`, `views/RandomizerView.tsx` | `randomizer_picks` table; filters in localStorage |
| Year in Review | `yearInReview/`, `actions/yearInReviewActions.ts`, `routes/yearInReviewRoutes.ts`, `completedGameStore.yearInReviewRows` | `useYearInReviewWorkflow.ts`, `views/YearInReviewView.tsx`, `views/yearInReview/*` (games open Completed Library detail; `GameShelf.tsx` shelves) | `year_in_review_settings` table |
| Artwork | `artwork/`, artwork routes | `artwork.ts`, `UpcomingView.tsx`, detail views, `ui/CoverScene.tsx` + `theme/coverTint.ts` (cover backdrop and tint) | artwork files and cached covers in app data |
| Wallpaper | wallpaper route and runtime storage | `wallpaperWorkflow.ts`, `WallpaperPanel.tsx`, `Backdrop.tsx` | wallpaper file in app data |
| Appearance | — | `theme/palettes.ts`, `theme/usePreferences.ts`, `ui/FramedPanel.tsx`, `styles.css` | palette ID in `settings` (`UI_PALETTE`) via `actions/preferencesActions.ts`, `routes/preferencesRoutes.ts`; localStorage as first-paint cache |
| Diagnostics | `diagnostics/`, diagnostic routes | settings/diagnostics UI | JSONL log in app data |
| Missing images | — | `ui/imageFallback.ts` (one capturing listener on `document`) and `img[data-image-failed]` in `styles.css` | — |

## Change rules

1. Start at the feature row above and find its external seam before editing implementation files.
2. Keep route modules thin; put behaviour in a deep action, store, read model, workflow, or adapter with a small interface.
3. Keep writes inside database stores/actions and app-data writes inside runtime modules. Actions own the write policy: each one runs through `runWrite(db, ...)` (queued behind other writes, one transaction). Routes never call `enqueueWrite`; they parse, `await` the action and return `sendActionResult`.
4. Keep renderer views focused on rendering and user intent; put state transitions in workflow modules.
5. Add or update the nearest seam test before moving a module. Avoid mass file moves: this tree uses relative imports across process areas, so a cosmetic move can create a large, fragile diff without improving locality.
6. After code changes, run `npm test`, `npm run typecheck` and `npm run build`. For packaged desktop changes, also run the platform-specific rebuild and `npm run dist` described in `AGENTS.md`.
7. Check `git status --short` before and after work. Treat `game-release-tracker/`, `dist/`, `node_modules/`, logs, databases, and user files as runtime/generated data, not source changes.

## Current organization assessment

The existing module seams are already coherent: process responsibilities are separated, backend domains have dedicated folders, and tests mirror the main seams. The safe professional improvement is discoverability and explicit ownership, which this map and the folder notes provide. A later structural refactor should be justified by a concrete seam or dependency problem, not by moving files for visual symmetry.
