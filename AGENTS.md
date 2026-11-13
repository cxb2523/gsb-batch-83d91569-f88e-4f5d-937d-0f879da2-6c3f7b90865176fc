# Agent Guide

This repo is a public Electron desktop app for Windows and Linux. Treat the packaged app and user-data flows as the real deliverable, not just source changes. For module ownership and safe change seams, read [`docs/CODEBASE_MAP.md`](docs/CODEBASE_MAP.md) before restructuring code.

## Working Directory

Current active workspace:

The repository root is the directory containing this file. Do not assume a Windows or WSL-specific absolute path.

Work on the current branch unless the user asks for a copy or branch. Keep changes scoped and reversible.

## User Preferences

- Explain what will change before risky edits.
- Prefer direct implementation once the user approves a plan.
- Keep Git history clean and traceable.
- Commit only approved checkpoints.
- Repackage the EXE after app behavior changes.
- If a fix fails, revert or isolate the failed change before piling on more patches.

## Required Checks

For normal code changes:

```bash
npm rebuild better-sqlite3
npm test
npm run typecheck
npm run build
```

For packaged desktop changes:

```bash
npm run dist
npm run smoke
```

`npm run smoke` starts the packaged build as a new user and opens every screen (on Linux without a display, `xvfb-run -a npm run smoke` after `npx electron-builder --linux dir`).

`npm run dist` rebuilds `better-sqlite3` for Electron. If you need to run Vitest after packaging, run `npm rebuild better-sqlite3` first so tests use the local Node ABI again.

If `electron-builder` fails under `dist\win-unpacked`, check whether a packaged `Game Release Tracker.exe` is still running and locking files before changing code.

## Build Outputs

Do not commit `dist/`, `build/` outputs, packaged EXEs, logs, databases, or user data unless explicitly requested. The useful packaged artifact path after `npm run dist` is:

`dist\Game Release Tracker-0.7.0-win.zip`

## Git Rules

- Check `git status --short` before editing and before committing.
- Do not revert user changes unless explicitly asked.
- Prefer one coherent commit per approved checkpoint.
- Use clear commit messages describing user-visible behavior and architecture cleanup.
- Before committing, inspect `git diff --cached --stat`.

## Architecture Vocabulary

Use the domain terms in `CONTEXT.md`. When improving architecture, talk about modules, interfaces, seams, depth, leverage, and locality.

## Frontend Shape

Important modules:

- `apps/frontend/src/App.tsx`: shell and view routing only
- `apps/frontend/src/useAppWorkflow.ts`: combines app-level workflows
- `apps/frontend/src/appShell.ts`: current view, operation-error banner, confirm/alert dialogs, and the `AppState` starting-state shape
- `apps/frontend/src/collectionWorkspace.ts`: list browsing shared by Upcoming and Completed Library (filters, genre, selection, Ctrl+A, bulk delete, return from detail to the same list and scroll position)
- `apps/frontend/src/collectionDeletion.ts`: the one delete flow for both collections, single and bulk (confirm, delete each, log, alert on failure)
- `apps/frontend/src/releaseWorkspace.ts`: release list/detail/sync/artwork/delete state (list reloads fetch only the list)
- `apps/frontend/src/useSettingsWorkflow.ts`: Settings page and the saved credential status
- `apps/frontend/src/useCompletedLibraryWorkflow.ts`: completed-library coordination
- `apps/frontend/src/views/ReleaseMediaGallery.tsx`: upcoming detail trailer/screenshots gallery
- `apps/frontend/src/views/ReleaseDetailEditors.tsx`: release title/detail editing controls
- `apps/frontend/src/releaseEditing.ts`: release edit patch shape and comparison rules
- `apps/frontend/src/detailSession.ts` / `candidateSearch.ts`: detail-page and IGDB search behaviour shared by both collections
- `tests/frontend/fakeApiClient.ts`: in-memory `ApiClient` for `<AppShell api={...}>` tests; prefer it over stubbing `fetch`
- `apps/frontend/src/useRandomizerWorkflow.ts` / `views/RandomizerView.tsx`: Randomizer filters, spin, reel and recent picks
- `apps/frontend/src/randomizerFilters.ts`: every Randomizer filter edit (pure; dedupes id lists, empty/off/blank stored as absent, chip label keys)
- `apps/frontend/src/useYearInReviewWorkflow.ts` / `views/YearInReviewView.tsx` / `views/yearInReview/*`: Year in Review data, chapters, GOTY picker, theme player, Save as image
- `apps/frontend/src/yearInReviewNavigation.ts`: pure chapter navigation reducer (carry on scrolling, momentum cooldown, keys); time is passed in
- `apps/frontend/src/wallpaperWorkflow.ts`: wallpaper picker and URL resolution
- `apps/frontend/src/ui/imageFallback.ts`: every `<img>` that fails to load is hidden so its frame shows empty; no per-image error handling needed
- `apps/frontend/src/theme/usePreferences.ts`: app-wide preferences saved in app data through `/api/preferences`: the HD-2D palette (localStorage is its first-paint cache) and Year in Review theme autoplay

Keep list/card payloads light. Fetch heavy fields like summary, screenshots, and trailers only on detail pages.

Build IGDB image URLs only through `artwork.ts` (`artworkSrc`, `igdbCoverSrc`, `cachedCoverSrc`, `screenshotSrc`). Detail pages use `cachedCoverSrc` (the backend cover cache, same-origin) so `ui/CoverScene.tsx` can read the cover's colour; an IGDB URL would taint the canvas.

## Package Footprint

- Only native modules (`better-sqlite3`) are `dependencies`. Everything else is bundled (Vite for the renderer, esbuild for main, preload and the backend child), so it is a `devDependency` and must not ship in `app.asar`.
- Keep large, rarely used backend modules off the boot path by loading them on first use (the sample data JSON files are loaded with a cached `import()`).
- See "Package footprint and boot cost" in `docs/DOCUMENTATION.md` before changing `build.files` or `electronLanguages`.

## Backend Shape

Important modules:

- `apps/backend/src/server.ts`: Fastify app factory and route registration
- `apps/backend/src/routes/*`: thin route modules
- `apps/backend/src/actions/*`: action modules for user workflows
- `apps/backend/src/database/*`: release persistence and reads
- `apps/backend/src/completed/*`: completed-library identity, matching, ratings, stores
- `apps/backend/src/sync/*`: upcoming IGDB sync planning, rules, enrichment
- `apps/backend/src/randomizer/*`: Randomizer query text, pure draw, pick history (writes only `randomizer_picks`)
- `apps/backend/src/releaseAlerts/*`: release alerts for watched games, handed to the desktop app once each (writes only `release_alerts_sent`)
- `apps/backend/src/releaseDates/*`: release date history: names each date change (delayed, announced, earlier) and is the only writer of `release_date_changes`
- `apps/backend/src/yearInReview/*`: Year in Review pure recap (`buildYearInReview`), thresholds, per-year settings (writes only `year_in_review_settings`)
- `apps/runtime/src/*`: app-data file storage and runtime path resolution

Database writes should go through existing store/action seams where possible. Keep route handlers small.

## Trailer Rules

Trailers are upcoming-release detail media only.

- IGDB `videos.video_id` and `videos.name` are fetched during normal sync.
- Store one sanitized YouTube id in `release_trailers`.
- Do not store arbitrary iframe URLs.
- Do not render iframes on list/card views.
- The thumbnail selects the trailer poster only.
- The centered play button mounts the iframe inline.
- Switching media, going fullscreen, or closing overlay should unmount playback when appropriate.

## Wallpaper Rules

Wallpaper belongs to app data.

- Desktop picker returns a relative route, normally `/api/wallpaper/current`.
- Backend serves the file with `Cache-Control: no-store`.
- Frontend resolves relative URLs against the current API base.
- Frontend adds a cache-busting query revision for display.
- Do not store raw image data in frontend state beyond temporary object URLs in browser fallback mode.

## Completed Library Rules

- The app's database is the Completed Library. There is no Excel import any more (removed in schema v18); games are added and edited in the app.
- Games are keyed by identity key: normalized title plus normalized user platform. Adding a game that matches an existing key updates that game.
- Every write of a rating's text (`rating_raw`) also sets its score (`rating_score`) through `completed/completedRating.ts`.
- Manual IGDB match overrides follow a game through renames.

## Native Module Gotcha

Electron stays on a version `better-sqlite3` publishes prebuilt binaries for (currently Electron 42, ABI 146; 12.11.1 has none for 43/44 yet), so `npm run dist` downloads the Windows binary instead of compiling SQLite, which would need Visual Studio build tools. Move to a newer supported Electron once a `better-sqlite3` release ships its prebuild (check `https://github.com/WiseLibs/better-sqlite3/releases/download/v<version>/better-sqlite3-v<version>-electron-v<abi>-win32-x64.tar.gz`).


`better-sqlite3` is native. There are two common rebuild states:

- Vitest/local Node wants the local Node ABI.
- Electron package wants Electron ABI.

Use:

```bash
npm rebuild better-sqlite3
```

before tests when the previous command was `npm run dist`.

Use:

```bash
npm run dist
```

after tests when the final deliverable is the EXE.

## Documentation

Keep these files aligned:

- `CONTEXT.md`: domain language and current decisions
- `AGENTS.md`: how agents should work in this repo
- `README.md`: short project intro and commands
- `docs/CODEBASE_MAP.md`: source-folder ownership, dependency direction, and safe seams
- `docs/DOCUMENTATION.md`: longer technical reference
- `docs/USER_GUIDE.md`: plain-English guide to every screen
- `docs/HOW_IT_WORKS.md`: the design and its decisions, for non-engineers
- `CHANGELOG.md`: what changed in each version, in plain language

If a feature changes domain meaning, update `CONTEXT.md` in the same checkpoint.

Refresh `CONTEXT.md`, `docs/DOCUMENTATION.md`, and `docs/USER_GUIDE.md` together when behavior or architecture changes. Keep the README command list and short project description aligned with the current package scripts.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (hachi23/game-release-tracker), via the gh CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.
