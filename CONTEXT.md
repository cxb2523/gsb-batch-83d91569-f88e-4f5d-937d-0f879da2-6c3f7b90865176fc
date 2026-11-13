# Game Release Tracker Context

This file is the project vocabulary and decision record for future work. Keep it current when a feature changes the meaning of a domain term.

## Product Shape

Game Release Tracker is a private Windows desktop app for two related jobs:

- tracking upcoming game releases from IGDB
- maintaining a personal completed-games library, added and edited in the app

A third, smaller tool, the Randomizer, suggests a random released game from the whole IGDB catalogue. Year in Review recaps each year of the Completed Library.

The app is not a public storefront. It should feel like a personal game journal: dense enough for repeated use, but visual enough to enjoy browsing covers, screenshots, trailers, notes, dates, and platform chips.

## Current Runtime Shape

- Electron main process owns the desktop window, app lifecycle, the tray icon, and native file pickers. Minimizing hides the window to the tray; closing it quits the app. **Start at login** (Settings → Sync, packaged app only) starts it with `--hidden`, straight into the tray; the operating system holds that choice (a Windows login item, a Linux autostart file), not app data.
- The backend is a Fastify child process with SQLite storage through `better-sqlite3`.
- The frontend is React/Vite. In packaged mode it loads from the fixed `app://renderer` origin, which the desktop app passes through to the backend, so localStorage and the V8 code cache survive restarts.
- Shared request/response shapes live in `shared/types.ts`.
- Runtime app-owned files such as wallpapers live under the app data directory, not frontend localStorage.

- A Linux app-data backup can be restored on first desktop launch through `GRT_RESTORE_DIR` (or from the backup beside the development root). New packages carry no personal data. Restore copies missing files into writable app data without overwriting an existing database.

## Domain Terms

### Release

An upcoming game tracked from IGDB or added manually. A release has a title, release date fields, category, publisher/developer/platform lists, artwork, screenshots, optional trailer metadata, and user flags.

Key modules:

- `apps/backend/src/database/releaseStore.ts` (the Release Store: every release write)
- `apps/backend/src/database/releaseReadModel.ts`
- `apps/frontend/src/releaseWorkspace.ts`
- `apps/frontend/src/views/UpcomingView.tsx`
- `apps/frontend/src/views/DetailView.tsx`

### Release Date Precision

How exactly a release's date is known: **Exact** (a day), **Month**, **Window** (a quarter, season or "early/late" phrase), **Year**, or **TBA**. Only an Exact date gets a countdown and a place on the calendar; every other precision shows its words ("Dec 2026", "Q4 2026", "2027"). IGDB gives a vague date a timestamp at the end of its period, so its displayed text, not the timestamp, decides the precision.

### Date Change

A change to a release's date that a sync brought in, kept in `release_date_changes` (schema v21) by `releaseDates/dateChanges.ts`. Its kind is **delayed** (a later date, or the date lost to TBA), **announced** (a sharper date inside the old period: "2027" becoming "Mar 14, 2027", or a TBA game getting a date) or **earlier** (moved up). Dates are compared as the periods they name ("2027" is all of 2027, "Q4 2027" October to December), never by sort date, because a vague date sorts by the start of its period when typed or given as words and by the end when IGDB sends a timestamp. The same date reworded is no change, nor is a date made less exact within its period. A date the user set by hand is kept by sync, so it records nothing. A hand edit that makes the date vague without giving a day clears the old day, and when it names no precision the words decide it ("Q4 2027" is a Window), as sync reads IGDB's. The Upcoming list shows the newest delay or move up ("Delayed from Mar 14, 2027") on the row and the featured panel, even after the date is later announced; an announced date shows only in the detail page's **Date history**. Deleting a release deletes its history.

### Release List Item

The lightweight card/list payload for release browsing. It should stay small: no trailer iframes, no heavy detail-only fields, no unnecessary screenshot payloads beyond what the UI really needs.

### Release Identity

One Release per IGDB game. A game added from IGDB search keeps its `manual-<uuid>` id and its `igdb_id`; the Sync Run finds it by `igdb_id` (`releaseStore.idForIgdbGame`) and updates that row instead of inserting `igdb-<id>`. Adding a game sync already tracks returns the tracked Release, or a 409 when that Release is hidden from Upcoming. A unique index on `releases.igdb_id` (schema v13) enforces this.

### User Override

A field the user edited on a release (title, publishers, developers, platforms, category, date fields). Each edit is stored in `manual_overrides` with source type `user`, and the IGDB Sync Run re-applies it, so edits survive sync. Fields the user never edited keep following IGDB.

### Release Detail

The detail payload for a single release. It may include screenshots, trailers, sources, IGDB URL, and richer metadata. Trailer playback belongs to the detail media gallery, not the list/card view.

### Completed Game

A personal finished game entry, added and edited in the app. Games imported from the retired Excel workbook keep their data (`source_type = 'excel'`, Excel genres, extra columns) but are edited like any other. Its rating text and score always agree: every write of `rating_raw` sets `rating_score` (`completed/completedRating.ts`), and a score sent without text is ignored.

Key modules:

- `apps/backend/src/completed/completedGameStore.ts`
- `apps/backend/src/completed/completedReadModel.ts`
- `apps/frontend/src/useCompletedLibraryWorkflow.ts`
- `apps/frontend/src/views/CompletedLibraryView.tsx`
- `apps/frontend/src/views/CompletedDetailView.tsx`

### Completed Library

The separate tab for completed games. It is separate from the upcoming release list. It has its own tables, filters, selection, detail page, and manual-add flow.

### Identity Key

The stable merge key for completed games. It is built from normalized title plus normalized user platform; adding a game whose key already exists updates that game. The Completed Library module (`completedGameStore.ts`) owns this key: renaming a game or changing its platform rebuilds the key and moves its match override, and a change that would collide with another game is refused (409). Game ids are fixed at creation and never follow renames.

### IGDB Match

The selected IGDB game for a completed game, picked when the game is added or with Fix match. Games matched automatically by the retired Excel sync may be flagged as needing review. The match override follows the game through renames.

### Artwork

Cover-like imagery displayed on cards and detail pages. Sources include IGDB artwork, IGDB cover, local uploads, and SteamGridDB.

### Screenshot

IGDB screenshot media displayed in detail galleries. For release details with a trailer, screenshots follow the trailer.

### Trailer

An upcoming-release-only YouTube trailer selected from IGDB `videos`. The app stores exactly one sanitized YouTube video id per release in `release_trailers`. Trailer iframes mount only after the user presses the play button.

Current behavior:

- trailer appears first in the upcoming detail media gallery
- screenshots follow after the trailer
- the thumbnail selects the trailer poster only
- the centered `Play trailer` button mounts the iframe inline
- fullscreen overlay is app-level and optional
- no trailer support for completed games in this pass

### Wallpaper

An app-owned background image selected through the desktop picker. The chosen image is copied into app data and served from `/api/wallpaper/current`.

Current behavior:

- backend route streams the current wallpaper with `Cache-Control: no-store`
- frontend resolves the relative wallpaper URL against the current API base
- frontend appends a display revision query string so replacing wallpaper forces reload
- the wallpaper is a backdrop image; the selected HD-2D palette owns all panel, accent, and text colors, except that a detail page sits in a **cover scene**: its game's cover, heavily blurred, is the backdrop, and the palette's surfaces, borders and accent blend toward the cover's main colour (`ui/CoverScene.tsx`, `theme/coverTint.ts`). Text colours stay the palette's
- covers shown on detail pages come through the **cover cache**: `GET /api/covers/:imageId` downloads the IGDB cover once into `<app data>/covers/` and serves it from the app's own origin, which is what lets the page read its colour
- framed panels keep controls readable above the image

### HD-2D Diorama appearance

The renderer uses a fixed 52px top navigation bar, framed panels, a featured release backdrop and compact upcoming rows. Completed games use a filter rail and 132×176 cover grid. Both Upcoming and Completed Library have a Genre filter: upcoming releases use IGDB genres stored in `release_genres` during sync; completed games match on Excel genres plus IGDB genres. Genre filtering happens in the frontend over the loaded list. There are no All Games or Watchlist tabs: the **watchlist** is the releases whose `watched` flag (in `user_release_state`) is on. **☆ Watch** on the featured panel or a detail page sets it, a ★ marks watched rows, and **Watched only** (More filters, the `watchedOnly` list query) shows just them. Watched games are the ones the app alerts you about. Twelve typed palettes supply eight CSS color roles; Abyss Gold is the default. The choice is saved in app data (the `UI_PALETTE` row of `settings`, through `GET /api/preferences` and `PUT /api/preferences/palette`); `grt.palette` in localStorage is a first-paint cache (it survives restarts now that the packaged window has a fixed origin; app data stays the saved choice). Wallpaper remains an app-owned image and does not supply theme colors. This is a presentation decision; release and completed-library workflows keep their existing domain rules.

### IGDB Gateway

The one module the backend uses to reach IGDB (`apps/backend/src/igdb/gateway.ts`). It is built once per backend from saved settings and shared by the Sync Run, manual search, completed-game matching, the Randomizer and the credential test, so they share one token and one rate limit. Besides `query`, it offers `count` (`<endpoint>/count`, which answers with one `{ count }` object) and `multiquery` (up to 10 named sub-queries in one request). Every request aborts after 10 seconds and fails like any other request; only 429 responses are retried. Tests substitute a fake gateway.

### Randomizer

The side-nav tab that picks one random released game from the whole IGDB catalogue, limited by filters the user sets: quick picks (JRPG, Anime, Made in Japan), similar to a game, series, platforms, genres and themes (include and exclude), tags (all of, plus excluded tags), game modes, camera view, rating and rating-count ranges, include unrated games, release years, remakes on/off, hide Completed Library games and hide Upcoming games. Every spin is limited to mainstream platforms: PlayStation, Xbox and Nintendo hardware plus PC; with no platform chosen, all of them count. JRPG and Anime each stand for a group of IGDB keywords. Made in Japan means a Japanese studio is credited as developer; it queries IGDB `involved_companies`, because filtering games by company country would also match Japanese publishers and localizers. Series matches any chosen IGDB franchise (broad, such as "Final Fantasy") or collection (a tighter series). Similar to spins only among the 10 games IGDB lists as similar to the seed game; when none of those is left after the filters and cooldown, it widens to games that at least two of them list as similar, before any recent pick may repeat. The pick card's **More like this** sets the seed to the pick and spins. By default the rating filters and the 5-rating floor leave out unrated games (about 90% of IGDB); include unrated turns them into "matches them, or has no rating yet". IGDB is the only candidate source: the Randomizer never adds rows to `completed_games` or `releases`. It only reads their `igdb_id`s to hide games the user already has.

Filters are a per-viewer preference saved as `grt.randomizer.filters` in localStorage; names of tags and series found by search are saved as `grt.randomizer.labels`. Genres, themes, game modes and camera views come from one IGDB `multiquery`, cached in backend memory for the life of the process. The platform list, popular tags and quick-pick keyword groups are a fixed catalog of IGDB ids. Any other tag is found by name through tag search.

Key modules:

- `apps/backend/src/randomizer/catalog.ts` (mainstream platforms, popular tags, quick-pick keyword groups)
- `apps/backend/src/randomizer/queryBuilder.ts` (filter validation, IGDB `where` text, empty-pool reason)
- `apps/backend/src/randomizer/draw.ts` (the pure draw and cooldown shrink)
- `apps/backend/src/randomizer/pickHistoryStore.ts`
- `apps/backend/src/actions/randomizerActions.ts`
- `apps/frontend/src/useRandomizerWorkflow.ts`
- `apps/frontend/src/views/RandomizerView.tsx`

### Spin

One press of the Spin button. A spin makes two IGDB requests (a `games/count`, then one page of games sorted by id) plus one extra count per cooldown shrink. Made in Japan counts and pages `involved_companies` rows instead, then loads those games: three requests. Similar to adds a similar-games lookup (cached per seed per backend process) and one count to decide whether to widen. Pools of up to 500 games are fetched whole and picked from exactly; larger pools are read through one 9-game window at a random offset. A short cover reel plays while the request runs; `prefers-reduced-motion` skips it.

### Pick

The game a spin returns. Every pick is recorded in `randomizer_picks` (trimmed to the newest 500). The pick card shows cover, title, year, genres, the mainstream platforms it is on, IGDB rating and rating count, themes, summary and a link to IGDB. An impossible filter set returns no pick and a plain reason instead of an error.

### Cooldown window

The IGDB ids of the last 50 picks, excluded from every spin. When the window would empty the pool, it halves (50, 25, 12, 6, 3, 1) and the response says `repeatAllowed`. It never drops below 1, so the previous pick only repeats when it is the only game that matches. Clear history deletes all picks, which resets the window.

### Year in Review

The top-bar tab that recaps one year of the Completed Library, like the "Wrapped" recaps other apps do. It reads the completed games whose completion year is that year (every precision) and is read-only over them: it never calls IGDB and never writes `completed_games` or `releases`. Its only write is the per-year settings row in `year_in_review_settings`. It opens full screen over the whole window (Escape or **✕ Leave** goes back to Upcoming) with a short Wrapped-style intro for the year (`YearIntro.tsx`; skipped by a click or any key, not replayed when coming back from a game's page). A chapter change sweeps a band in the new chapter's colour across the screen, and each chapter's heading and cards animate in. The intro, wipes and particles only run with a real frame loop and without reduced motion (`canAnimate` in `motion.ts`). Five chapters, one at a time, each a **realm** with its own illustrated scene, colours, card style and lettering: Overview is The Atlas (a sea chart with a port per month), Taste The Grimoire (a spellbook whose magic circle spells out your genres), Ratings The Forge, Timing & Habits The Astrolabe (its pointer aims at your busiest month) and Game of the Year The Throne, where the GOTY's own art fills the window. The scenes are SVG drawn in code, so they ship no image files. Keeping on scrolling past a chapter's bottom carries on into the next one; tabs and the arrow keys also work. A card whose data is missing is left out, and each chapter's footnote says which games it had to leave out (year-only finishes are counted in totals, ratings and taste but not in month charts, streaks or day-one finishes). No hours played anywhere. The current year is shown "so far". **Save as image** offers a horizontal poster (1920×1080 cover grid for screens) or a vertical one for a phone's Reddit feed (a dense 1080-wide grid, 6–7 covers a row for a typical year, about a phone screen tall, the GOTY first; names in 24px+ bold and the platform on its own line, so they read at a glance at phone width without opening the image). Both show every game finished that year with name, platform and rating, the GOTY crowned, drawn on a canvas (`views/yearInReview/poster.ts`, covers through the same-origin cover cache) and saved as a PNG through a save dialog (desktop only). Every game shown opens its Completed Library detail page, whose back button returns to the same year, chapter and open list. Categories are clickable: a month or rating bar, a genre, theme or platform, "rated 9 or higher" and the day-one list each open a **shelf**, the games in that category unrolled under the chapter's cards as covers with their title and (platform). It closes with its Close button, the same category again, a chapter change or Escape. For this the summary carries each game's finish `month` and each genre, theme and platform share its game `ids`.

Key modules:

- `apps/backend/src/yearInReview/buildYearInReview.ts` (the pure recap, the only interface of the recap logic)
- `apps/backend/src/yearInReview/thresholds.ts` (every tunable number)
- `apps/backend/src/yearInReview/yearInReviewSettingsStore.ts`
- `apps/backend/src/actions/yearInReviewActions.ts`
- `apps/frontend/src/useYearInReviewWorkflow.ts`, `yearInReviewNavigation.ts` (pure chapter navigation), `views/YearInReviewView.tsx`
- `apps/frontend/src/views/yearInReview/GameShelf.tsx` (shelf keys → games, the unrolled shelf, the cover tiles)
- `apps/frontend/src/views/yearInReview/RealmScenes.tsx` (the four drawn scenes, the GOTY art backdrop, the particles)
- `apps/desktop/src/saveImageIpc.ts` (Save as image: writes the poster PNG)

### Game of the Year (GOTY)

The year's headline game in Year in Review: the highest-rated finish, ties going to the later finish, or the user's saved override while that game is still in the year. With no rated games it is the year's last finish, labelled as such. The override is a completed-game id, so it survives renames; deleting the game clears it.

### Theme music

A YouTube video id saved per year for the Game of the Year. It is pasted as a link; only the 11-character id is kept (`shared/youtubeLink.ts`). It plays when the user presses **▶ Play theme**, or by itself when a year with a theme link opens if **theme autoplay** is on (Settings → Appearance, the `UI_THEME_AUTOPLAY` settings row, off by default). It plays in the background: the `youtube-nocookie` player is loaded but invisible, and a small pill shows it is playing with a Stop button. It keeps playing across chapters, follows the year on screen, and a Play or Stop holds for that year and link; it stops when leaving Year in Review. The desktop window allows autoplay without a click (`autoplayPolicy` in `main.ts`) for this; trailers still mount only when their play button is pressed.

### Player type

A title from fixed rules over the year's stats, first match wins: The Critic, The Loyalist, The Explorer, The Time Traveller, The Day-One Hero, The Completionist, otherwise The Adventurer. Each comes with its reason.

### Finish order

How Year in Review orders a year's finishes: exact dates, then month-only entries (as if on the last day of their month), then year-only entries, then title. First and last, the rest-of-the-year covers under the GOTY and the GOTY tie-break all use it.

### Sync Run

An upcoming-release IGDB sync. It should be serialized, logged, and return a status object rather than throwing raw errors into the UI. Each game is saved in its own savepoint: a game that fails is rolled back, logged and counted, and the rest of the run is kept (status `partial`). A run never stays marked `running` after an error, and a run cut off by closing the app is marked `failed` (`interrupted`) when the backend next starts. Sync should not refetch or rewrite more than necessary.

### Release Alert

A system notification about a watched game: **out today** (its exact release day is the user's today) or a recent **Date Change** (recorded in the last 7 days and after the game was watched; older changes are history). `releaseAlerts/releaseAlerts.ts` hands each alert out once (`POST /api/alerts/take`, remembered in `release_alerts_sent`), and nothing while alerts are off in Sync Settings. The desktop app asks 15 seconds after startup and every 5 minutes (`apps/desktop/src/releaseAlerts.ts`), so alerts from a background sync arrive while the window is in the tray. Clicking one brings the window back and opens that game. Hidden games never alert.

### Sync Settings

What the Sync Run looks for, set on Settings → Sync (`sync/syncSettingsStore.ts`): the **tracked publishers** (IGDB companies by id, in `tracked_publishers`; a game counts when a tracked company is credited as its publisher or developer), the **platform families** (PC, Xbox, PlayStation, Nintendo Switch; `PLATFORM_FAMILIES` maps each to IGDB platforms), the **track-from date**, **auto-sync** (at startup, then a check every 30 minutes while the app runs, each syncing when the last successful sync is over 12 hours old) and **release alerts** (on by default). A new library tracks no publishers, every platform family, releases from January 1 of the current year, and syncs only when asked; "Add suggested publishers" adds a starter set by exact IGDB name. The Release Policy (`sync/releasePolicy.ts`, `createReleasePolicy(rules)`) turns these into the sync's accept/reject rules. A stored release is eligible whenever it has a date; the track-from date is applied when Upcoming is listed, so changing it rewrites nothing.

### Sample Library

What a new user can load from the first-run welcome to try the app without IGDB keys (`demo/demoLibrary.ts`, `demo/demoLibrary.json`): 30 upcoming releases and 46 finished games, all real games with their public IGDB data (covers, artwork, trailers, genres, ratings), and made-up personal data (ratings, finish dates, platforms, notes). Finishes fall in the previous calendar year (a full Year in Review) and in this year up to today; upcoming dates move by whole months so the list starts last month (a game or two just out, the rest to come), or this month in January, because the default "from January 1" filter would hide last year's games; a vague date ("Q4 2026", "2027") moves by whole years, rounded up, so it stays after the exact dates around it. It is written through the normal stores, and the ids it created are kept in the `DEMO_LIBRARY` settings row, so **Remove sample data** deletes exactly those rows and nothing the user added. Sample releases carry no IGDB id, so a later sync adds the user's own copies instead of taking them over. While the sample is loaded and no IGDB keys are saved, the Randomizer spins among 267 released games bundled with it (`demo/randomizerSample.json`, real IGDB data with genre, theme, mode and platform ids) through the same draw, with genre, theme, mode, platform, rating and year filters applied in memory (`randomizer/sampleCatalog.ts`); tags, quick picks, series, similar games, Made in Japan and camera view need IGDB keys.

### Scroll Restoration

When a user opens a release detail and goes back, the release list should return to the opened game position rather than the top. This belongs to the release workspace flow.

### Cross-platform restore

The desktop runtime discovers a game-release-tracker backup beside the development root or an explicit `GRT_RESTORE_DIR`. New packages carry no personal data. It restores only missing app-owned files: game-release-tracker.db, wallpaper, artwork, and logs. The backup remains unchanged and an existing Windows database wins.

### Error handling

Backend failures return a stable safe `{ error }` response while the full error is written to the app diagnostic log. Renderer failures show a recovery screen with a reload action. Main-process and backend-child failures are logged and reported through a native desktop error dialog when possible. A failed startup always ends the process: `handleStartupFailure` logs, shows the error, stops any backend that started, then quits; a backend that never reports ready is killed by `waitForBackendReady` so it cannot keep the database and port locked.

## Current Database Notes

Current schema version is `21`. v14 dropped the unused backlog, game-length and pick-history tables that v10 had created. v15 created the new `randomizer_picks` table for the IGDB Randomizer. v16 runs the eligibility and completion-date repairs once; before v16 they ran on every launch. Startup does no data repair; a future eligibility policy change adds a migration that re-runs `refreshAllEligibility`. v17 adds `year_in_review_settings` (one row per year: GOTY override, theme music id); an older EXE refuses a library upgraded to v17. v18 retires the Excel import (clears `missing_from_latest_import`, drops `completed_library_sync_state`; the Excel-era columns stay so no data is lost) and fills `rating_score` from `rating_raw` where it was missing: games added or re-rated in the app used to save only the text, so they showed as unrated. The desktop app also deletes the old workbook copy (`completed-library/` in app data) at startup. v19 indexes `sources(release_id)` and removes the insert/update FTS triggers; the Release Store refreshes search after saving child rows. After each finished sync run, `sync_log` keeps rows for the latest 20 runs. v20 adds `tracked_publishers` (replacing the built-in publisher list and its `publisher_sync_state` lookup cache, whose found companies become tracked publishers) and recomputes eligibility from dates alone. v21 adds `release_date_changes` (date history; see Date Change).

Important tables:

- `releases`
- `release_artworks`
- `release_screenshots`
- `release_trailers`
- `user_release_state`
- `sources`
- `blocked_releases`
- `completed_games`
- `completed_match_overrides`
- `randomizer_picks`
- `year_in_review_settings`

`release_trailers` belongs to upcoming release detail behavior only.

## Architecture Direction

Prefer deep modules with small interfaces and local behavior:

- route modules should be thin and delegate to actions/stores; actions own the write queue and the transaction (`runWrite`), so every action is atomic and serialized
- read models should build payloads, not mutate state
- stores should own database write invariants
- frontend workflow hooks should own state transitions
- view modules should render and emit user intent
- runtime modules should own app-data file storage
- process and renderer failure reporting should use the diagnostic log seam

Recent useful seams:

- `ReleaseMediaGallery` owns trailer/screenshot navigation and playback
- `ReleaseDetailEditors` owns release title/detail edit UI
- `releaseEditing` owns release edit patch shape and comparison rules
- `wallpaperWorkflow` owns wallpaper URL resolution and picker flow
- API keys are encrypted at rest (`secretCipher.ts`) with a data key only the OS account can unlock (`credentialKey.ts`, Electron safeStorage)
- The local backend answers only this app: loopback Host header plus a per-launch token on `/api` calls (`requestGuard.ts`); `main.tsx` builds the one token-carrying `ApiClient`
- `appShell` owns the current view, the operation-error banner and injectable confirm/alert dialogs
- `useSettingsWorkflow` owns the saved credential status; the release workspace owns only the release list and Upcoming sync status, and a list reload fetches only the list
- `collectionWorkspace` owns list browsing shared by Upcoming and the Completed Library: filters, debounced search, genre filter, selection, Ctrl+A, bulk-delete bookkeeping and the return from a detail page to the same list view and scroll position; each collection supplies only how to load and delete, its list/detail views and its item data attribute
- `collectionDeletion` runs every delete in both collections, single and bulk, with the same confirm, diagnostics and failure alert
- `completedGameStore` is the Completed Library module: Identity Key, manual create, edit and match application
- `releaseStore.edit` records user edits as overrides so sync keeps them
- Workflows hand views whole sub-workflow objects (`manual`, `detail`, `sync`); `App.tsx` selects the view and passes the object, without renaming fields
- `detailSession` owns the detail page for both collections (open with fallback, adopt the item an edit returns, refresh the list, one error policy); `candidateSearch` owns the IGDB search-then-pick step of both add forms
- `AppShell` accepts an `api` prop, so frontend tests can drive the whole app with the in-memory `tests/frontend/fakeApiClient.ts` instead of stubbing `fetch`
- `theme/usePreferences` owns the app-wide preferences in app data: the active palette (cached in localStorage for first paint) and theme autoplay
- `randomizer/draw` is pure: filters and IGDB I/O are injected, so the draw and cooldown rules are tested without IGDB; `useRandomizerWorkflow` owns filters, spinning and recent picks
- `buildYearInReview` is pure (rows and `today` in, summary out) and reads completed games through `completedGameStore.yearInReviewRows`; `yearInReviewNavigation` is a pure reducer with time passed in, so chapter carry-on and momentum rules are tested without a DOM

## Safety Rules

- The app's data folder is `%APPDATA%\Game Release Tracker` on Windows (set in `main.ts`, not taken from the npm package name), so it never shares a library with another build of the package.
- Do not store raw wallpaper bytes or absolute localhost URLs in localStorage.
- The packaged app reads API keys only from Settings (stored encrypted); `IGDB_*` and `STEAMGRIDDB_*` environment variables are a development fallback and are removed from the packaged backend's environment.
- No telemetry: diagnostics stay in the local log. The app contacts only IGDB (and Twitch for its token), IGDB's image CDN, SteamGridDB when a key is saved, and YouTube (`youtube-nocookie.com`) when a trailer or theme music plays.
- Do not mount YouTube iframes on list/card views.
- Do not add trailer URLs manually in v1; trailer source is IGDB only.
- Do not change release-calendar behavior when working on completed-library features.
- Do not rewrite Git history unless the user explicitly asks.
- The Randomizer never writes to the release or completed-library tables; it writes only `randomizer_picks`.
- A spin makes at most two IGDB requests (three with Made in Japan) plus one count per cooldown shrink.
- Every spin is limited to mainstream PlayStation, Xbox, Nintendo and PC platforms.
- IGDB none-of filters are written `field != (...)`; `field = !(...)` is a syntax error.
- A spin never returns the previous pick while two or more games match.
- Year in Review never writes completed-game or release rows; it writes only `year_in_review_settings`. Theme music stores a sanitized YouTube id, never a URL. Its hidden player is the only iframe that can mount without a click, and only with theme autoplay on; trailers always wait for Play.
