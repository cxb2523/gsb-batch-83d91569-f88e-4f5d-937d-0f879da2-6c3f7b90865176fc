# Game Release Tracker — Comprehensive Technical Documentation

## 1. Project Overview

A private desktop application for tracking upcoming video game releases, maintaining a personal library of completed games, and picking a random game to play from IGDB (the Randomizer). Built as an Electron app with a separate Fastify backend process, SQLite database, IGDB API integration, and a React frontend styled with a "journal" aesthetic.

- **Version**: 0.7.0
- **Platform**: Windows (NSIS installer + zip) and Linux (`.deb` for Mint/Ubuntu/Debian + AppImage)
- **License**: Private
- **Repo**: `hachi23/game-release-tracker`

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Electron Main                      │
│            apps/desktop/src/main.ts                  │
│   - Creates BrowserWindow (1280×820)                │
│   - Spawns backend child process                     │
│   - IPC handlers for wallpaper + diagnostics         │
│   - Preload script (context isolation)               │
└──────────────┬──────────────────┬────────────────────┘
               │                  │
       spawns process        loads URL
               │                  │
┌──────────────▼──────┐  ┌────────▼────────────────────┐
│  Fastify Backend     │  │  React Frontend (Vite)      │
│  apps/backend/src/   │  │  apps/frontend/src/         │
│  - REST API on       │  │  - App.tsx (shell + router) │
│    127.0.0.1:PORT    │  │  - Views (React components) │
│  - better-sqlite3    │  │  - Workflows (hooks)        │
│  - IGDB sync engine  │  │  - styles.css (journal)     │
│  - Artwork storage   │  │  - API client               │
└──────────────────────┘  └─────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│              shared/types.ts                         │
│   All TypeScript interfaces shared between           │
│   frontend and backend (ReleaseListItem,            │
│   CompletedGameDetail, SyncStatus, etc.)            │
└─────────────────────────────────────────────────────┘
```

### Process model
- **Electron main** (`apps/desktop/src/main.ts`): requests single-instance lock, starts backend child process, creates the browser window and its tray icon (minimize hides to the tray), registers IPC handlers for native file dialogs (wallpaper image), and reports process failures through the diagnostic log and a native error dialog.
- **Backend child** (`apps/backend/src/child.ts`): spawned as a `tsx` process, opens a Fastify server on an ephemeral port, writes the port to stdout for the main process to read, and exits after logging uncaught failures so the desktop shell can report them.
- **Frontend**: loaded from `http://127.0.0.1:5173` (dev) or `dist/frontend/index.html` (packaged). Communicates with backend via `fetch` to `http://127.0.0.1:PORT/api/*`.

### Error handling

- Fastify's `setErrorHandler` records the request, status, message, and stack through the shared diagnostic logger. It sends a generic 5xx message so implementation details do not leak into the UI.
- `ErrorBoundary` wraps the React shell, records render failures through `/api/diagnostics/log`, and presents a reload action.
- The backend child and Electron main process register crash handlers. They write process-failure events to the same app-data JSONL log and use a native dialog when the desktop shell can still respond.
- Settings exposes the diagnostic log path and an **Open diagnostics log** action for support and troubleshooting.
- The log records app events, UI actions, failed requests (`http.response`, 4xx/5xx) and slow ones (`http.slow`, over 1 s), by route pattern rather than raw URL, so search text stays out. It rotates at 5 MB and keeps three older files (`.log.1`-`.log.3`). Logging is best effort: a failed write or a rotation clash between the app and the backend is dropped rather than stopping the app. Secret-like keys (tokens, keys, Authorization, client IDs, cookies) and secrets inside text (`client_secret=`, `access_token=`, `Bearer …`) are redacted.

### Shared types (`shared/types.ts`)
All cross-boundary TypeScript interfaces live here. Key types:
- `ReleaseListItem` / `ReleaseDetail` — upcoming releases
- `CompletedGameListItem` / `CompletedGameDetail` — completed games
- `SyncStatus` / `CompletedLibrarySyncStatus` — sync run results
- `ReleaseArtwork` — artwork with source (`artwork` | `cover` | `local` | `steamgriddb`)
- `IgdbGameLike` — raw IGDB API response shape
- `RandomizerFilters` / `RandomizerOptions` / `RandomizerSpinResponse` / `RandomizerHistoryItem` — Randomizer filters, option lists, spin result and pick history

## 3. Database Schema

SQLite via `better-sqlite3`. Migrations in `apps/backend/src/database/migrations.ts` (version-tracked in `schema_version` table, currently at **schema v21**; startup runs only pending migrations, no per-launch data repair). Before upgrading an existing library, the database is copied with `VACUUM INTO` to `backups/<name>.v<old>.<time>.db` next to it; the three newest backups are kept. A library whose schema is newer than the app is refused unchanged, and the startup dialog shows that reason.

### Core tables

| Table | Purpose | Key columns |
|---|---|---|
| `releases` | Upcoming releases | `id`, `title`, `normalized_title`, `date_text`, `release_date`, `date_precision`, `category`, `eligible`, `effective_sort_date`, `archived_at` |
| `release_artworks` | Artwork per release | `release_id`, `image_id`, `source`, `sort_order` |
| `user_release_state` | Per-user flags | `release_id`, `hidden`, `watched`, `released` |
| `release_alerts_sent` | Release alerts already shown (v21), so each shows once; deleted with the release | `release_id`, `alert_key` (`out:<day>` or `change:<id>`), `sent_at` |
| `release_date_changes` | Date history recorded by sync (v21); deleted with the release | `release_id`, `kind` (delayed, announced, earlier), `from_text`, `to_text`, `from_sort_date`, `to_sort_date`, `sync_run_id`, `changed_at` |
| `manual_overrides` | User edits (title, lists, category, dates) and seeded date overrides that sync re-applies | `release_id`, `field`, `value`, `source_type`, `source_url` |
| `sources` | Source URLs per release | `release_id`, `source_name`, `source_url`, `field` |
| `blocked_releases` | Deleted+blocked games | `id`, `igdb_id`, `normalized_title`, `title`, `reason` |
| `sync_runs` | Sync execution log | `id`, `status`, `added`, `repaired`, `skipped`, `failed`, `message` |
| `sync_log` | Per-game sync decisions | `sync_run_id`, `title`, `action` (accept/reject), `reason` |
| `releases_fts` | FTS5 virtual table | `title`, `normalized_title`, `publishers`, `developers`, `sources` (refreshed by the Release Store; delete trigger removes deleted releases) |

### Completed library tables

| Table | Purpose | Key columns |
|---|---|---|
| `completed_games` | Completed games | `id`, `title`, `normalized_title`, `identity_key`, `source_identity_key`, `user_platform`, `rating_raw`, `rating_score`, `hours_played`, `completion_date`, `completion_month`, `completion_year`, `completion_precision`, `notes`, `developer`, `publisher`, `igdb_id`, `cover_image_id`, `match_status`, `screenshots_json`, `source_type`, `missing_from_latest_import` |
| `completed_match_overrides` | Manual IGDB match overrides | `identity_key`, `normalized_title`, `user_platform`, `igdb_id` |

Schema v10 added IGDB theme, game-mode and rating columns plus `hours_played` to `completed_games`; v11 added `release_genres`; v12 added `completed_games.source_identity_key`; v13 made `releases.igdb_id` unique; v14 dropped the unused backlog, game-length and pick-history tables v10 had also created; v15 created the new `randomizer_picks` table; v16 runs the eligibility and completion-date repairs once; v17 adds `year_in_review_settings`; v18 retires Excel import state and fills missing `rating_score` values from `rating_raw`; v19 indexes `sources(release_id)` and removes duplicate FTS insert/update triggers; v20 adds `tracked_publishers` and drops `publisher_sync_state`.

### Randomizer table

| Table | Purpose | Key columns |
|---|---|---|
| `randomizer_picks` | Randomizer pick history; the newest 50 ids form the cooldown window. Trimmed to the newest 500 rows after each insert | `id`, `igdb_id`, `title`, `cover_image_id`, `filters_json`, `picked_at` |

### Year in Review table

| Table | Purpose | Key columns |
|---|---|---|
| `year_in_review_settings` | One row per year: the Game of the Year override and the theme music's YouTube id. `goty_completed_id` references `completed_games(id)` `on delete set null` | `year`, `goty_completed_id`, `music_video_id`, `updated_at` |

### Identity keys
Completed games use an `identity_key` = `${normalizeText(title)}|${normalizeText(platform)}`. This key links `completed_games` to `completed_match_overrides`. `completedGameStore.edit` owns title/platform changes: it rebuilds the key in both tables and refuses collisions. `source_identity_key` is left over from the retired Excel import and no longer read.

## 4. Backend

### Server (`apps/backend/src/server.ts`)
Fastify instance with request/response logging hooks and a centralized error handler.

**Request guard** (`requestGuard.ts`, installed first): every request must address a loopback host (`127.0.0.1`, `localhost`, `[::1]`), which refuses DNS-rebinding pages; every `/api` call must carry the `x-grt-token` header with the per-launch secret the Electron main process generates and passes to the backend (`GRT_API_TOKEN`) and to the renderer (preload `getApiToken`). Only the app shell, `/assets`, `GET /api/wallpaper/current`, `GET /api/artworks/local/*` and `GET /api/covers/*` are exempt, because `<img>` and page loads cannot send headers. Without a token (backend started directly for development) only the host check applies. Every response also carries a Content-Security-Policy (own scripts only; images from IGDB, i.ytimg.com and SteamGridDB; frames only from youtube-nocookie.com) and `X-Content-Type-Options: nosniff`.

Registers route modules:
- `releaseRoutes` — CRUD for upcoming releases
- `completedRoutes` — CRUD + sync + match for completed games
- `randomizerRoutes` — Randomizer option lists, spin and pick history
- `yearInReviewRoutes` — Year in Review years, yearly summary and per-year settings
- `preferencesRoutes` — app-wide preferences kept in app data (the palette)
- `artworkRoutes` — upload/delete/reorder artwork
- `syncRoutes` — IGDB sync trigger + status
- `settingsRoutes` — credentials management
- `wallpaperRoutes` — wallpaper image storage
- `diagnosticRoutes` — log endpoints
- `adminRoutes` — admin actions

Unexpected 5xx errors are logged with their stack and return only `{"error":"Something went wrong. Check the diagnostics log for details."}`. Expected 4xx errors retain their user-facing message.

### REST API

#### Releases
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/releases` | List releases (filters: search, publisher, category, platform, datePrecision, includeHidden, includeReleased, watchedOnly) |
| GET | `/api/releases/:id` | Get release detail |
| POST | `/api/releases/manual` | Create manual release |
| PATCH | `/api/releases/:id` | Update release (title, publishers, developers, platforms, category, dateText, releaseDate, datePrecision, releaseWindow, hidden, watched, released) |
| DELETE | `/api/releases/:id?block=true` | Delete release, optionally block from re-sync |
| POST | `/api/releases/:id/artworks/local` | Upload local artwork (base64) |
| GET | `/api/covers/:imageId` | An IGDB cover through the cover cache: downloaded once (`t_cover_big_2x`) into `<app data>/covers/`, then served from disk. 400 for a non-IGDB id, 404 when it can't be downloaded |
| DELETE | `/api/releases/:id/artworks/:imageId` | Delete artwork |
| PATCH | `/api/releases/:id/artworks/order` | Reorder artworks |

#### Completed games
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/completed-games` | List completed games (filters: search, platform, year, month, rating, dateState) |
| GET | `/api/completed-games/:id` | Get completed game detail |
| POST | `/api/completed-games/manual` | Create manual completed game |
| PATCH | `/api/completed-games/:id` | Update completed game (title, userPlatform, ratingRaw, ratingScore, completionDate, completionMonth, completionYear, completionPrecision, developer, publisher, notes, genres, platforms) |
| DELETE | `/api/completed-games/:id` | Delete completed game |
| GET | `/api/completed-games/:id/match-candidates` | Search IGDB for match candidates |
| POST | `/api/completed-games/:id/match` | Apply IGDB match (saves metadata + screenshots) |

#### Randomizer
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/randomizer/options` | Genre, theme, game-mode and camera-view lists from one IGDB multiquery (cached in memory per backend process), plus the fixed mainstream platform list and popular tags |
| GET | `/api/randomizer/series?search=` | IGDB franchises and collections whose name contains the text, from one multiquery, each tagged `kind` |
| GET | `/api/randomizer/games?search=` | Full games (no DLC or bundles) by IGDB search, for choosing the Similar to game |
| GET | `/api/randomizer/tags?search=` | Any IGDB keyword whose name contains the text (at least 2 characters), for the tag filters. 400 for shorter text, 409 without IGDB credentials |
| POST | `/api/randomizer/spin` | Body `RandomizerFilters` → `RandomizerSpinResponse`. 400 for invalid filters, 409 without IGDB credentials, 200 `{ pick: null, reason }` for an empty pool; IGDB failures return the safe 500 |
| GET | `/api/randomizer/history?limit=20` | Recent picks, newest first (max 100) |
| DELETE | `/api/randomizer/history` | Clear pick history, which resets the cooldown window |

#### Year in Review

| Method | Path | Description |
|---|---|---|
| GET | `/api/year-in-review/years` | `{ years: { year, count, inProgress }[] }`: every year with a finish, newest first, plus the current year |
| GET | `/api/year-in-review/:year` | `YearInReviewSummary` for the year (1970–2100, else 400). A year with no games returns `count: 0` |
| PUT | `/api/year-in-review/:year/settings` | Body `{ gotyCompletedId?: string \| null, musicLink?: string \| null }` (absent = unchanged, null = clear) → the updated summary. 400 for a bad year, a link that isn't a YouTube video, or a game not finished that year |

#### Sync
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sync/igdb` | Trigger IGDB sync run |
| GET | `/api/sync/status` | Get last sync status |
| GET | `/api/demo` | `{ loaded }`: whether the sample library is loaded |
| POST | `/api/demo` | Loads the sample library → `{ loaded, releases, completedGames }`; 409 if already loaded |
| DELETE | `/api/demo` | Removes exactly the sample rows → `{ loaded: false }` |
| GET | `/api/sync/settings` | Sync settings: tracked publishers, platform families, track-from date, auto-sync |
| PUT | `/api/sync/settings` | Body `{ platforms?, trackFrom?, autoSync?, alerts? }` → the updated settings; 400 for no platforms, an unknown platform, a bad date or a non-boolean auto-sync or alerts |
| POST | `/api/alerts/take` | Release alerts not yet shown for watched games (`{ items: [{ releaseId, kind, title, body }] }`), each marked shown; empty while alerts are off. The desktop app shows them as notifications |
| GET | `/api/sync/publishers/search?q=` | IGDB companies whose name contains the text (at least two letters), most published first; 409 without IGDB keys |
| POST | `/api/sync/publishers` | Body `{ id, name }` tracks an IGDB company → the updated settings |
| POST | `/api/sync/publishers/suggested` | Tracks the suggested publishers IGDB knows by exact name → the settings plus `notFound`; 409 without IGDB keys |
| DELETE | `/api/sync/publishers/:id` | Stops tracking a company; 404 if it wasn't tracked |

#### Settings
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Get settings status |
| PATCH | `/api/settings` | Save IGDB credentials |
| DELETE | `/api/settings/credentials` | Clear credentials |
| POST | `/api/settings/test-credentials` | Test IGDB credentials |
| GET | `/api/preferences` | `{ palette, themeAutoplay }`: the saved palette id (or null) and whether Year in Review theme music starts by itself (false until turned on) |
| PUT | `/api/preferences/palette` | Save the palette id `{ palette }` (a short lower-case slug, else 400) |
| PUT | `/api/preferences/theme-autoplay` | Save `{ themeAutoplay }` (a boolean, else 400) |

#### Diagnostics
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/diagnostics/log` | Append a renderer event or error to the redacted JSONL diagnostic log |

### Sync engine (`apps/backend/src/sync/`)

The IGDB sync flow:
1. `syncRun.startSync()` — singleton mutex, prevents concurrent syncs (owns the run lifecycle)
2. `syncRun.execute()` — creates a `sync_runs` record, discovers candidates, fetches SteamGridDB artwork, persists
3. `igdbCandidateSource.discoverIgdbCandidates()` — queries IGDB for every game a tracked publisher (by IGDB company id, from Settings → Sync) is credited on, from the track-from year on. With no tracked publishers the run fails with a message telling the user to add some
4. `releasePolicy.chooseBestReleaseDate()` picks the earliest date on a tracked platform. IGDB dates vague releases at the end of their period (Dec 31 for "2027"), so the date's `human` text sets the precision: a bare year is Year, "Mmm YYYY" is Month, a quarter, half, season or early/mid/late phrase is Window, anything else is Exact. Only Exact dates get countdowns and calendar cells
5. `releaseSyncPlanner.prepareSyncCandidate()` — applies the Release Policy built from the sync settings (`createReleasePolicy`: game type, excluded edition names, tracked platform families, tracked publisher or developer, track-from date) and normalizes each game once per run; both later steps use the result
6. SteamGridDB enrichment (`syncArtworkEnrichment.ts`) — outside the write queue, looks up artwork only for accepted, unblocked games that still lack provider artwork, four lookups at a time
7. In the write queue, per game: `releaseSyncPlanner.planReleaseSync()` decides add/repair/skip against freshly read merge state and the block list, then `releaseStore.save()` upserts the release

### Data stores

- **`releaseStore`** (`apps/backend/src/database/releaseStore.ts`): the only writer of the release tables. Upserts releases with media, sources and FTS; artwork, user state, date overrides and detail edits (recorded as user overrides); delete with optional block, `isBlocked`, `unblock`; IGDB identity (`idForIgdbGame`); the merge state sync reads (`loadMergeState`); curated seeds (`applySeed`); and the startup eligibility refresh, run in one transaction
- **`completedGameStore`** (`apps/backend/src/completed/completedGameStore.ts`): the only writer of completed games: manual create (the rating score follows the rating text), apply a manual match (override + metadata together), edit (title/platform rebuild identity_key and move the match override), delete; plus list/detail reads

### Randomizer (`apps/backend/src/randomizer/`)

1. `queryBuilder.parseRandomizerFilters()` validates the body; every value that reaches IGDB is a number or boolean.
2. `randomizerActions.spin()` gathers exclusions: the cooldown window (last 50 pick ids), then Completed Library `igdb_id`s (unless `hideCompleted: false`) and Upcoming `igdb_id`s (when `hideUpcoming: true`). The list is capped at 1,000 ids, newest first.
3. `queryBuilder.buildRandomizerWhere()` builds one `where` from the base clauses (`game_type = (0,10[,8,9,11])`, released, has a cover, `platforms` = the chosen or all mainstream platforms), the filters and `id != (...)` (IGDB rejects the `id = !(...)` form). Tags are all-of (`keywords = [a,b]`); each quick pick adds its own any-of keyword clause; rating and rating-count filters are min–max ranges. The default rating-count floor is 5. With Made in Japan, `buildJapanDeveloperWhere()` targets `involved_companies` instead (`developer = true & company.country = 392` plus the same clauses prefixed `game.`), and the page's game ids are loaded with one more `games` request. Series becomes `(franchises = (...) | collections = (...))`. Include unrated wraps the rating and rating-count clauses as `((...) | total_rating = null)`. Similar to adds `id = (candidates)`: the seed's `similar_games`, or, once those are used up, those plus games listed as similar by at least two of them.
4. `draw.drawRandomGame()` runs `games/count`, then fetches either the whole pool (≤ 500 games) or one 9-game window at a random offset (`sort id asc`), and picks uniformly. If the cooldown window would empty the pool it halves (50 → 1) and recounts; `repeatAllowed` is then true. An empty page retries once from offset 0.
5. The pick is recorded in `randomizer_picks` through `runWrite`.

IGDB I/O and the rng are injected into `draw.ts`, so the draw and cooldown rules are unit-tested without IGDB. The Randomizer never writes to `releases` or `completed_games`.

### Year in Review (`apps/backend/src/yearInReview/`)

1. `yearInReviewActions` reads the year through `completedGameStore.yearInReviewRows(year)`: the year's rows as a `CompletedReviewRow` projection (list fields plus notes, IGDB release date, developer, publisher, themes, game modes, critic score, rating count and screenshots), the genres and platforms of every earlier year, and finishes per year.
2. `buildYearInReview({ year, today, games, earlier, years, settings })` is pure and the only interface of the recap: overview, taste, ratings (with the player type), timing, Game of the Year and the covers in finish order. Every tunable number is in `thresholds.ts`. Genres use the shared `completedGenres` rule (saved + IGDB genres), the same as the Completed Library Genre filter. Ratings round half up only in the spread chart (`shared/wholeRating.ts`, which the frontend's rating shelves use too). Each game carries its finish `month` and each genre, theme and platform share its game `ids`, so the frontend can list the games behind any category.
3. The settings PUT parses the music link with `shared/youtubeLink.ts` and checks the chosen game is in that year before `yearInReviewSettingsStore.save()` runs through `runWrite`. The store is the only reader and writer of `year_in_review_settings`.

`today` is passed in (`createBackendApp({ today })` in tests), so the current year and "so far" never depend on the clock inside the calculation.

### Write queue
`apps/backend/src/database/writeQueue.ts` — serializes all write operations through a single promise chain. Ensures SQLite writes are not concurrent.

## 5. Frontend

### Shell (`apps/frontend/src/App.tsx`)
- `AppShell` component receives `apiBaseUrl` and optional `initialState`
- `ErrorBoundary` (`apps/frontend/src/ErrorBoundary.tsx`) wraps the shell, reports render failures, and offers a reload action
- 52px top navigation with 6 tabs: Upcoming, Calendar, Completed Library, Randomizer, Year in Review, Settings
- Topbar has the brand, the view buttons, the palette menu and Sync now. Add game lives in Upcoming; wallpaper controls live in Settings.
- View switching via `view` state (`gallery` | `calendar` | `detail` | `completed-library` | `completed-detail` | `settings` | `add` | `completed-add` | `randomizer` | `year-in-review`). Randomizer and Year in Review load lazily on first visit

### Views (`apps/frontend/src/views/`)

| Component | File | Purpose |
|---|---|---|
| `UpcomingView` | `UpcomingView.tsx` | Featured release backdrop, compact grouped rows, search, genre and other filters, bulk actions |
| `CalendarView` | `CalendarView.tsx` | Month-grid calendar with artwork thumbnails on exact-date releases |
| `DetailView` | `DetailView.tsx` | Release detail with two framed panels, media gallery, inline title and full details editing |
| `CompletedLibraryView` | `CompletedLibraryView.tsx` | Completed games in a 132×176 cover grid with gold frames for ratings of 9 or above, grouped or grid mode |
| `CompletedDetailView` | `CompletedDetailView.tsx` | Completed game detail with screenshots-only gallery, ruled metadata, inline title + full details editing, IGDB match candidates |
| `ManualReleaseView` | `ManualReleaseView.tsx` | Form to add a release manually |
| `CompletedManualGameView` | `CompletedManualGameView.tsx` | Form to add a completed game manually |
| `RandomizerView` | `RandomizerView.tsx` | Randomizer filter rail, Spin button, cover reel (which eases to a stop on the pick, `ReelLanding`, before the card grows out of it; skipped for reduced motion), pick card, empty-pool reason, Settings hint, Recent picks strip |
| `YearInReviewView` | `YearInReviewView.tsx` + `yearInReview/*` | Year picker, chapter tabs and stage (slide transitions, carry on scrolling), one file per chapter, the GOTY finale with its picker and music form, the theme player, Save as image (a horizontal or vertical poster of the year's games drawn by `yearInReview/poster.ts`). Full screen (`position: fixed` over the top bar; Escape or Leave calls `onExit`). Each chapter is a realm: `.yir[data-realm]` swaps the palette tokens, `--realm-font` and the card dressing, and `RealmScenes.tsx` crossfades an SVG scene (Atlas, Grimoire, Forge, Astrolabe) or the GOTY's screenshot, with canvas particles and a small pointer parallax (both off for reduced motion). Games open their Completed Library detail page (`OpenGame` context in `parts.tsx`); clickable categories open a shelf (`ShelfControl` in `parts.tsx`, keys resolved by `resolveShelf` in `GameShelf.tsx`) unrolled under the cards. Its CSS (`yearInReview/yearInReview.css`) and the realm fonts (`yearInReview/realmFonts.css`: Cinzel, Cinzel Decorative, IM Fell English SC, Uncial Antiqua, Pirata One) load with the lazy chunk |
| `SettingsView` | `SettingsView.tsx` | Tabs: Appearance (palettes, wallpaper), API keys, Sync (`settings/SyncSettingsPanel.tsx`: tracked publishers, platforms, track-from date, auto-sync) and Diagnostics. Opens on API keys while the IGDB keys need attention |
| `WallpaperPanel` | `WallpaperPanel.tsx` | Wallpaper choose/clear controls |

### Workflows (React hooks)

| Hook | File | Purpose |
|---|---|---|
| `useAppWorkflow` | `useAppWorkflow.ts` | Top-level hook combining app shell + release workspace + completed library workflow + settings + wallpaper |
| `useAppShell` | `appShell.ts` | Current view, operation-error banner, UI event logging, unexpected-error reporting, injectable confirm/alert dialogs; also defines `AppState`, the optional pre-loaded starting state |
| `useCollectionWorkspace` | `collectionWorkspace.ts` | Shared list behaviour for Upcoming and Completed Library: filters + debounced search, genre filter, selection, Ctrl+A, bulk-delete bookkeeping |
| `useReleaseWorkspace` | `releaseWorkspace.ts` | Release list loading (a reload fetches only the list), sync status (loaded at startup and after a sync; a sync the app did not start, such as the startup auto-sync, is polled every 3 s and the list reloads when it ends) and navigation; composes the list (`useCollectionWorkspace`), detail and Add game workflows |
| `useDetailSession` | `detailSession.ts` | Shared detail-page behaviour: open with fallback, apply an edit and adopt the returned item, refresh the list, one error policy |
| `useCandidateSearch` | `candidateSearch.ts` | Shared IGDB "search, then pick" state for both add-game forms; also defines `ManualAddWorkflow`, the one shape both add-game workflows return and both add-game views take whole |
| `useReleaseDetailWorkflow` | `useReleaseDetailWorkflow.ts` | Release detail: rename, edit, artwork upload/remove/promote, delete |
| `useReleaseManualGameWorkflow` | `useReleaseManualGameWorkflow.ts` | Add game form, IGDB candidate search and save |
| `useSettingsWorkflow` | `useSettingsWorkflow.ts` | Settings page: saved credential status (loaded on first open), credential drafts, save, clear and test |
| `useSyncSettingsWorkflow` | `useSyncSettingsWorkflow.ts` | Settings → Sync: loads the sync settings on first open; publisher search, track, untrack and the suggested set; platform, track-from and auto-sync changes save at once |
| `useCompletedLibraryWorkflow` | `useCompletedLibraryWorkflow.ts` | Completed games loading, grouped/grid view mode, bulk delete; list browsing via `useCollectionWorkspace` (genres = saved + IGDB). Returns its sub-workflows whole (`sync`, `detail`, `manual`) instead of re-exporting their fields |
| `useCompletedManualGameWorkflow` | `useCompletedManualGameWorkflow.ts` | Completed manual game draft state, save payload shaping, reset, and detail handoff |
| `useCompletedGameDetailWorkflow` | `useCompletedGameDetailWorkflow.ts` | Completed game detail on `useDetailSession`: IGDB matching, delete, rename, edit |
| `useCollectionSelection` | `collectionSelection.ts` | Selection-set state used inside `useCollectionWorkspace` |
| `useRandomizerWorkflow` | `useRandomizerWorkflow.ts` | Randomizer filters (saved as `grt.randomizer.filters` in localStorage), option lists and history loaded on first open, spin with a ~1.5 s reel (skipped for reduced motion), clear history, missing-credential state |
| `useYearInReviewWorkflow` | `useYearInReviewWorkflow.ts` | Year list, selected year's summary (reloaded on each visit), saving the GOTY override and theme music, and the place (year, chapter, open shelf) to return to from a game's detail page |
| `wallpaperWorkflow` | `wallpaperWorkflow.ts` | Wallpaper choose/clear via IPC |

### Year in Review navigation (`apps/frontend/src/yearInReviewNavigation.ts`)
A pure reducer, `(state, event) → state`, with events `wheel`, `scrolled`, `settled`, `key` and `tab`; time is passed in. Scrolling on past a chapter's bottom builds "pull" only after the scroll has rested at the edge for 150 ms (or the chapter has finished sliding in, so short chapters work); 160 px of wheel within 600 ms carries on into the next chapter, and pulling up at the top returns to the previous chapter's bottom. After a change, wheel input is ignored until it has been quiet for 400 ms (trackpad momentum). ←/→, Home/End, PageDown/Space at the bottom and PageUp at the top also move; keys typed in form fields and the GOTY forms are ignored. Cards render visible and only rise in where an `IntersectionObserver` exists; numbers render final and count up on top.

### API client (`apps/frontend/src/api/client.ts`)
`createApiClient(baseUrl)` returns an `ApiClient` with typed methods for every backend endpoint. Uses `fetch` with JSON content-type.

### Styling (`apps/frontend/src/styles.css`)
- **Theme**: HD-2D Diorama. Eight CSS color roles come from `theme/palettes.ts`; `theme/usePreferences.ts` applies the selected palette and saves it in app data (`PUT /api/preferences/palette`, the `UI_PALETTE` settings row), reading it back on launch with `GET /api/preferences`. localStorage (`grt.palette`) is a first-paint cache; it survives restarts because the packaged window has the fixed `app://renderer` origin. Abyss Gold is the default.
- **Fonts**: bundled Marcellus display and Alegreya Sans body fonts.
- **Layout**: fixed top bar and stage; every content block over an image uses the double-border `FramedPanel` with four ornaments.
- **Wallpaper**: app-owned image used as a backdrop. Palette colors stay stable when wallpaper changes.
- **Cover scene**: Upcoming and Completed Library detail pages are wrapped in `ui/CoverScene.tsx`. The game's cover (from the cover cache) fills the background at a heavy blur, and `theme/coverTint.ts` reads its main colour from a 32×32 canvas sample (greys, blacks and whites skipped, brightness normalised). `.cover-scene--tinted` in `styles.css` mixes that colour into `--c-bg`, `--c-panel`, `--c-input`, `--c-border` and `--c-accent` (their untinted values are kept as `--base-*` at `:root`) and recomputes the derived shades, with panels 70% opaque so the blurred cover shows through; the colour variables are registered with `@property` so the change fades over 600 ms. A cover that can't be read (cross-origin, colourless) leaves the palette as it is.
- **Missing images**: `ui/imageFallback.ts` (installed on `document` in `main.tsx`) marks any `<img>` that fails to load with `data-image-failed`, and `styles.css` hides it, so an offline or removed cover leaves its frame empty instead of showing the browser's broken-image icon. A later successful load clears the mark.
- **Welcome**: an empty library shows the welcome choices in the Upcoming rail and a "What you can do" panel (`WelcomeTour` in `UpcomingView.tsx`) beside it.
- **Views**: Upcoming selects a featured release from compact rows; Completed Library has a filter rail and 132×176 cover grid. Calendar, list, detail, add, and Settings screens use the same frames and tokens.

## 6. Desktop (Electron)

### Main process (`apps/desktop/src/main.ts`)
- Single-instance lock; starting the app again brings the running window back, even from the tray
- `releaseAlerts.ts`: release alerts as system notifications. `startReleaseAlerts` schedules the checks; `createSystemNotifier` is the adapter for Electron's `Notification` (the app icon; on Windows under the app's AppUserModelID), holding each one until clicked or closed, with a fallback for refused ones. It takes `POST /api/alerts/take` with the API token 15 s after startup and every 5 min; a click brings the window back and sends `open-release` to the page. Where Windows refuses a notification (the `failed` event: an app with no Start-menu shortcut, such as the zip build), the tray shows it as a balloon whose click does the same. Without notification support it does nothing
- Background sync: `sync/autoSyncSchedule.ts` checks 3 s after the backend starts and then every 30 min while it runs, and starts a sync when auto-sync is on and the last successful sync is over 12 hours old (`shouldAutoSync`, which reads SQLite's UTC timestamps through `shared/sqliteTime.ts`). Coming back from the tray (the page becoming visible) reloads the list and sync status
- `startAtLogin.ts`: Settings → Sync **Start with Windows, in the tray**. Windows keeps it as a login item (`app.setLoginItemSettings` with `--hidden`); Linux as `~/.config/autostart/game-release-tracker.desktop`, whose `Exec` runs the AppImage (`$APPIMAGE`) or the executable with `--hidden`. A packaged app only (installer, zip or AppImage), so development runs never register; it registers the program at its current path. The bridge also reports the platform, which names the switch. IPC `start-at-login` / `set-start-at-login` (only the app's frame may change it). Started with `--hidden`, the window stays in the tray unless the tray could not be created
- `trayWindow.ts`: minimizing hides the window to a tray icon (the app icon: `build/icon.ico` on Windows, `build/icon.png` scaled to 32 px elsewhere, both shipped in the package). A click or **Open Game Release Tracker** in the tray menu shows, restores and focuses it; **Quit** quits. Closing the window still quits. If the tray cannot be created, minimize stays a normal minimize, so the window is never hidden without a way back
- IPC handlers: `api-base-url`, diagnostics log path/open, wallpaper file dialog, `save-image` (Save as image)
- Backend lifecycle: spawn on startup, graceful shutdown on quit (3s timeout). The hidden window is created while the backend boots, and the page loads once the backend reports its port
- Unexpected main-process and backend-child failures are logged before a native error dialog/quit path
- Window: 1280×820, min 920×620, context isolation and sandbox enabled, node integration disabled, DevTools only in development
- `appProtocol.ts`: the packaged renderer's fixed `app://renderer` origin. Every request under it (page, hashed assets, `/api`) is passed to the backend's random-port URL, so the renderer keeps one origin across launches (localStorage, V8 code cache) and needs no CORS. YouTube embeds get an `https://io.github.hachi23.game-release-tracker/` Referer, which YouTube requires from apps without a web origin (player error 153 otherwise)
- `windowGuards.ts`: the window only ever shows the app; http(s) links (including `target="_blank"`) open in the default browser via `shell.openExternal`, and other schemes are refused. The `api-token` and `save-image` IPCs answer only a frame showing the app
- Permission requests are refused except fullscreen (trailers)
- Electron fuses (package.json `build.electronFuses`, applied by electron-builder): `RunAsNode`, `EnableNodeOptionsEnvironmentVariable`, `EnableNodeCliInspectArguments` and `GrantFileProtocolExtraPrivileges` are off, so the shipped executable cannot be reused as a plain Node runtime or opened to a debugger through Node flags. The backend child runs through `utilityProcess`, which needs none of them. Check a build with `npx @electron/fuses read --app <exe>`
- `credentialKey.ts`: a random 256-bit data key, stored only as `credential-key.bin` encrypted with Electron `safeStorage` (DPAPI on Windows), is passed to the backend (`GRT_CREDENTIAL_KEY`); the backend encrypts API keys with it before they reach SQLite (`enc:v1:` values) and seals plain-text values from older versions at startup. A key file the OS can no longer decrypt is kept as `credential-key.bin.unreadable` (later ones get `.2`, `.3`, …; none is overwritten) and a new key is made; Settings shows the affected API keys as "can no longer be read - enter it again". If the key cannot be stored at all (for example a read-only data folder or a keychain error), the app still starts and values stay unencrypted. Without OS encryption (or in development) values stay as they are

### Preload (`apps/desktop/src/preload.ts`)
Exposes a safe IPC bridge to the renderer for the API base URL and per-launch API token, diagnostics, wallpaper, and `saveImage(png, name)` operations, `onOpenRelease(callback)`, which a clicked release alert uses to open that game, and `getStartAtLogin()` / `setStartAtLogin(on)`.

### IPC modules
- `wallpaperIpc.ts` — native file dialog for wallpaper image selection
- `appDataIpc.ts` — Settings → Diagnostics: **Open log folder**, and **Delete all app data**, which (after a native confirm) stops the backend, removes the app's own files from the data folder (database, covers, artworks, wallpaper, backups, logs, credential key), clears the renderer's stored data and restarts the app. Only the app's own frame may ask
- `saveImageIpc.ts` — Save as image: takes the poster's PNG bytes from the page (checks the PNG signature and size), a save dialog (Pictures folder, `.png` only, safe file name), then writes the file. No image library

The diagnostics log lives under the app data `logs` directory as `game-release-tracker.log`. It is JSONL, and secret-like fields are redacted by `diagnostics/logger.ts`.

## 7. Runtime layer (`apps/runtime/src/`)

- `layout.ts` — resolves paths for dev vs packaged (frontend index, preload script, data directory, backend entry)
- `wallpaperStorage.ts` — reads/writes wallpaper image in the data directory

The desktop runtime discovers a backup beside the development root or through an explicit `GRT_RESTORE_DIR`, then copies missing app-owned files into the writable data directory on startup. It never overwrites an existing database. New packages carry no personal data.

### Package footprint and boot cost

- Only native modules the packaged app loads at runtime belong in `dependencies` (`better-sqlite3`). Fastify is bundled into `child.js` by esbuild, and React, React DOM and the `@fontsource` packages into `dist/frontend` by Vite, so they are `devDependencies` and electron-builder leaves them out of `app.asar`.
- `dist/apps/frontend` (the `tsc` copy of the renderer) is excluded from the package; the renderer is served from `dist/frontend`.
- The `build.files` globs drop the SQLite amalgamation source from `better-sqlite3`. Only `en-US` Chromium locale packs ship (`electronLanguages`).
- `apps/frontend/src/fonts.css` declares Latin and Latin Extended woff2 faces only.
- The sample data (`demo/demoLibrary.json`, about 100 KB, and `demo/randomizerSample.json`, about 280 KB) is loaded on first use with a cached `import()`, which esbuild turns into a lazily run wrapper inside `child.js`. The backend no longer evaluates it at every start (about 12 to 15 ms off backend startup on a fast machine; more on slow ones).



## 8. External APIs

### IGDB (igdb.com)
- Used for: discovering upcoming releases by publisher, fetching game details (cover, artworks, screenshots, summary, genres, platforms, developers, publishers), and the Randomizer's catalogue counts, pages and option lists
- Auth: OAuth2 client credentials flow (`client_id` + `client_secret` → `access_token`)
- Gateway: `apps/backend/src/igdb/gateway.ts` — the one IGDB entry point, created once per backend from saved settings and passed to routes, actions and sync through the route context. It keeps one client per credential set (one token, one shared 4 req/s rate limit) and owns all IGDB query text except the Randomizer's, which `randomizer/queryBuilder.ts` builds. It exposes `query`, `count` (`<endpoint>/count`) and `multiquery`
- Timeout: every request aborts after 10 s and fails like any other request; only 429 responses are retried
- Client: `apps/backend/src/igdb/client.ts` (HTTP adapter used by the gateway)
- Token management: `apps/backend/src/igdb/token.ts`
- Credentials stored in: SQLite settings table or environment variables
- Diagnostic logging: secret-like values are redacted before file writes

### SteamGridDB (steamgriddb.com)
- Used for: enriching cover art with higher-quality community-sourced images
- Client: `apps/backend/src/steamgriddb/client.ts`
- API key stored in: SQLite settings table

## 9. Testing

- **Framework**: Vitest (`vitest.config.ts`)
- **Frontend tests** (`tests/frontend/`): Vitest coverage for rendering/navigation, workflows, API behavior, wallpaper behavior, and the renderer error boundary
- **Backend tests** (`tests/backend/`): Vitest coverage for API routes, database/migrations, sync planner, IGDB client, SteamGridDB client, settings, artwork, completed library, diagnostics, and error handling
- **Desktop tests** (`tests/desktop/`): IPC, lifecycle, wallpaper storage
- **Packaged smoke test** (`scripts/smoke-packaged.mjs`, `npm run smoke [path to app]`): starts a packaged build with a throwaway profile and `--remote-debugging-port`, loads the sample library, opens every top-bar screen, quits, and fails on a page exception, a console error, an error banner, a slow exit, or a `fail`/`error`/`crash` event in the app's log. It talks to the DevTools protocol directly, so it needs no test packages and works with the fuses above. Every DevTools request has a 10-second limit and the whole run a 3-minute one, so an app that fails to start (for example a native error dialog) fails the test quickly instead of hanging it. CI runs it under `xvfb-run` on a `--linux dir` build; the release workflow runs it on the Windows build, the installed `.deb` and the AppImage (with `APPIMAGE_EXTRACT_AND_RUN=1`, since runners have no FUSE)
- If database tests report a `better-sqlite3` ABI mismatch, run `npm rebuild better-sqlite3` before running Vitest again. Run `npm run dist` afterward when the final deliverable is the packaged Electron app.

## 10. Build & Distribution

### Commands
```
npm run dev           # Vite dev server (127.0.0.1:5173)
npm run dev:backend   # Backend only (tsx)
npm run build         # TypeScript compile + Vite build + esbuild bundles → dist/
npm run test          # All tests
npm run test:frontend # Frontend tests only
npm run test:backend  # Backend tests only
npm run rebuild       # electron-rebuild (recompiles better-sqlite3 for Electron)
npm run dist          # Full pipeline: build + rebuild + electron-builder
npm run smoke         # Packaged smoke test (after dist)
```

### Output
- `dist/frontend/` — compiled React app (index.html + assets)
- `dist/apps/` — compiled backend + desktop TypeScript; `scripts/bundle.mjs` then writes the three packaged entry points (`desktop/src/main.js`, `desktop/src/preload.js`, `backend/src/child.js`) as esbuild bundles over the tsc output
- `dist/Game Release Tracker-0.7.0-win.zip` — zipped app, extract and run (no install)
- `dist/Game Release Tracker Setup 0.6.3.exe` — NSIS installer (~89 MB)
- `dist/game-release-tracker_0.6.3_amd64.deb` — Linux package (~91 MB); installs to `/opt/Game Release Tracker`, adds a Games menu entry
- `dist/Game Release Tracker-0.6.3.AppImage` — Linux, runs without installing (~117 MB)

### Electron builder config (package.json `build` field)
- `appId`: `io.github.hachi23.game-release-tracker`
- `asar`: true (with `better-sqlite3` unpacked). `files` ships only the three bundles, `dist/frontend` and `better-sqlite3` with its two runtime modules (`bindings`, `file-uri-to-path`)
- `afterPack`: `scripts/afterPack.cjs` removes `dxcompiler.dll` and `dxil.dll` (WebGPU's shader compiler; the app draws with canvas 2D)
- Windows targets: `nsis` (installer) + `zip`
- Linux targets: `deb` + `AppImage`, category `Game`, `desktopName` `game-release-tracker.desktop` (so the running window matches its menu entry), maintainer set to the GitHub no-reply address
- Release workflow (`.github/workflows/release.yml`): Windows and Linux jobs each build, run the tests and the packaged smoke test (Linux installs the `.deb` with apt and also smoke-tests the AppImage), then a publish job attaches all four files to the release with the changelog section as notes
- Icon: `build/icon.ico`

## 11. Data flow summary

### Upcoming releases sync
```
User clicks "Sync now"
  → Frontend: api.syncNow() → POST /api/sync/igdb
  → Backend: syncRun.startSync()
  → syncRun: discover IGDB candidates → fetch SteamGridDB art → persist
  → Returns SyncStatus { added, repaired, skipped, failed }
  → Frontend reloads release list
```

### Editing a game title
```
User clicks "Edit title" on detail page
  → Inline input appears with current title
  → User types new title, clicks Save
  → Frontend: api.patchRelease(id, { title }) or api.patchCompletedGame(id, { title })
  → Backend (release): releaseStore.edit() — updates fields, records a user override, keeps category index, eligibility and FTS in step
  → Backend (completed): completedGameStore.edit() — rebuilds identity_key, moves the match override, 409 on collision
  → Frontend: reloads detail + list
```

### IGDB match for completed game
```
User clicks "Fix match" on completed detail
  → Frontend: api.getCompletedMatchCandidates(id) → GET /api/completed-games/:id/match-candidates
  → Backend: searches IGDB by title, ranks candidates → returns list
  → User clicks "Use match" on a candidate
  → Frontend: api.saveCompletedMatch(id, igdbId) → POST /api/completed-games/:id/match
  → Backend: saves match override, fetches full game details, saves metadata (cover, screenshots, summary, genres, platforms)
  → Frontend: reloads detail
```

## 12. File index

```
apps/
  backend/src/
    server.ts                    Fastify app factory
    child.ts                     Backend entry point (spawned by Electron)
    actions/releaseActions.ts    Create/update/delete release logic
    actions/randomizerActions.ts Randomizer options cache, spin, pick history
    actions/yearInReviewActions.ts  Year in Review summary, years list, settings validation
    artwork/
      localArtworkStorage.ts     Save local artwork files to disk
      releaseArtworkWorkflow.ts  Artwork add/remove/reorder workflow
    completed/
      completedRating.ts         Rating text to 0..10 score
      completedGameStore.ts      Completed Library module: identity, manual create, edit, match apply
      completedIdentity.ts       identity_key + id generation
      completedIgdbMatcher.ts    The one Completed IGDB matcher: credential check, cached search, ranking, details (candidates / metadataFor / bestMatch)
      completedReadModel.ts      Completed game list/detail/identity read queries
    database/
      db.ts                      Database connection + pragma setup
      migrations.ts              Schema migrations (v1-v19)
      rowHelpers.ts              Shared nullable, JSON, and number row conversion helpers
      releaseReadModel.ts        Read queries (list/get release)
      releaseStore.ts            Release Store: every release write (upsert, media, FTS, overrides, blocks, seeds, eligibility)
      writeQueue.ts              Serialized write queue
    diagnostics/logger.ts        File-based diagnostic logger
    igdb/
      client.ts                  IGDB API client (rate limit, retries, 10 s timeout)
      gateway.ts                 The one IGDB entry point (query, count, multiquery)
      token.ts                   OAuth2 token management
    routes/
      actionResult.ts            Standardized action result sender
      adminRoutes.ts             Admin endpoints
      artworkRoutes.ts           Artwork CRUD routes
      completedRoutes.ts         Completed games routes
      randomizerRoutes.ts        Randomizer routes
      yearInReviewRoutes.ts      Year in Review routes
      context.ts                 Shared route context type
      diagnosticRoutes.ts        Log endpoints
      releaseRoutes.ts           Release CRUD routes
      settingsRoutes.ts          Settings routes
      syncRoutes.ts              Sync trigger + status routes
      wallpaperRoutes.ts         Wallpaper routes
    randomizer/
      queryBuilder.ts            Filter validation, IGDB where/count/page text, empty-pool reason
      draw.ts                    Pure draw: pool sizing, random window, cooldown shrink
      pickHistoryStore.ts        randomizer_picks reads/writes, trimmed to 500
      catalog.ts                 Mainstream platforms, popular tags, quick-pick keyword groups
    yearInReview/
      buildYearInReview.ts       Pure yearly recap (and the years list)
      thresholds.ts              Every tunable Year in Review number
      yearInReviewSettingsStore.ts  year_in_review_settings reads/writes
    releaseAlerts/
      releaseAlerts.ts           Release alerts for watched games (out today, date changes), each handed out once
    releaseDates/
      dateChanges.ts             Date history: names a change (delayed, announced, earlier); only writer of release_date_changes
    settings/
      settingsStore.ts             The settings table: credential keys (encrypted at rest), env fallback, seed version
      secretCipher.ts              AES-256-GCM sealing of credentials with the desktop app's data key
      settingsCredentialModule.ts  Credential status for Settings + credential test via the app's IGDB gateway
    steamgriddb/client.ts        SteamGridDB API client
    sync/
      autoSyncSchedule.ts        When auto-sync runs: at startup, then every 30 min while the app is open
      igdbCandidateSource.ts     Discover games from IGDB by publisher
      overrides.ts               Override loading
      releaseMerge.ts            Merge state loading
      releaseSyncPlanner.ts      Add/repair/skip decision logic
      releasePolicy.ts           Upcoming release policy: candidate rules, date choice, eligibility, IGDB game -> Release
      syncArtworkEnrichment.ts   SteamGridDB artwork enrichment
      syncRun.ts                 Single sync execution
      syncStatus.ts              Sync status queries
  desktop/src/
    main.ts                      Electron main process
    preload.ts                   Preload script (IPC bridge)
    backendProcess.ts            Spawn/stop backend child
    desktopLifecycle.ts          Startup/shutdown lifecycle
    wallpaperIpc.ts              Wallpaper file dialog IPC
    appProtocol.ts               app://renderer origin, passed through to the backend
    appDataIpc.ts                Open log folder; delete all app data
    saveImageIpc.ts              Save as image (save-image IPC)
    trayWindow.ts                Minimize to tray: tray icon, its menu, bringing the window back
  frontend/src/
    main.tsx                     React entry point
    ErrorBoundary.tsx            Renderer failure recovery and diagnostics reporting
    App.tsx                      App shell + view router
    styles.css                   HD-2D palette and frame CSS
    artwork.ts                   Artwork and screenshot URL helpers
    api/client.ts                API client (all endpoints)
    api/debounce.ts              Debounce utility
    appShell.ts                  View, operation banner, dialogs, UI logging
    collectionWorkspace.ts       Shared list browsing (filters, genre, selection, bulk delete, return to list + scroll position)
    collectionSelection.ts       Selection-set state inside collectionWorkspace
    releaseWorkspace.ts          Release workflow hook
    releaseEditing.ts            Release edit patch shape and comparisons
    useAppWorkflow.ts            Top-level workflow combiner
    useCompletedLibraryWorkflow.ts  Completed library workflow hook
    useCompletedGameDetailWorkflow.ts   Completed detail workflow
    useCompletedManualGameWorkflow.ts   Completed manual-entry workflow
    collectionDeletion.ts        Every delete (single and bulk, both collections): confirm, delete each, log, alert on failure
    releaseDeletion.ts           Upcoming delete modes (delete / delete and block) over collectionDeletion
    releaseGroups.ts             Group releases by date heading
    completedGroups.ts           Group completed games by month
    useRandomizerWorkflow.ts     Randomizer filters, spin and history hook
    randomizerFilters.ts         Pure Randomizer filter edits (dedupe, empty/off/blank = absent, label keys)
    useYearInReviewWorkflow.ts   Year in Review data: years, summary, settings
    yearInReviewNavigation.ts    Pure chapter navigation reducer
    youtube.ts                   YouTube embed and poster URLs (trailers, theme player)
    wallpaperWorkflow.ts         Wallpaper workflow hook
    views/
      UpcomingView.tsx           Upcoming release list and feature card
      CollectionControls.tsx     Genre field, bulk-action bar, sync state shared by list views
      CalendarView.tsx           Month-grid calendar
      DetailView.tsx             Release detail (edit title + details)
      CompletedLibraryView.tsx   Completed games library
      CompletedDetailView.tsx    Completed game detail (edit title + details + match)
      ManualReleaseView.tsx      Add release form
      CompletedManualGameView.tsx  Add completed game form
      RandomizerView.tsx         Randomizer filters, reel, pick card, recent picks
      YearInReviewView.tsx       Year in Review header, tabs, chapter stage, theme player
      yearInReview/              Chapters (Overview, Taste, Ratings, Timing, GOTY), parts, shelves, realm scenes, ThemePlayer, CSS, fonts
      SettingsView.tsx           Settings + sync
      WallpaperPanel.tsx         Wallpaper controls
      completedPresentation.ts   Completion date labels
  runtime/src/
    layout.ts                    Dev/packaged path resolution
    wallpaperStorage.ts          Wallpaper image storage
shared/
  types.ts                       All shared TypeScript types
  constants.ts                   Shared constants
  completedGenres.ts             Saved + IGDB genres, one rule for both sides
  youtubeLink.ts                 Pasted YouTube link -> video id
tests/
  backend/                       backend API, migration, workflow, diagnostics, and error-handling tests
  desktop/                       desktop IPC and lifecycle tests
  frontend/                      frontend rendering, workflow, and error-boundary tests
build/
  icon.ico / icon.png / icon.svg  App icons
```

## 13. Environment variables

See `.env.example`. Credentials can be provided via env vars OR saved in-app via Settings:
- `IGDB_CLIENT_ID`
- `IGDB_CLIENT_SECRET`
- `IGDB_ACCESS_TOKEN` (optional, auto-generated from client ID/secret)
- `STEAMGRIDDB_API_KEY` (optional, for richer cover art)
