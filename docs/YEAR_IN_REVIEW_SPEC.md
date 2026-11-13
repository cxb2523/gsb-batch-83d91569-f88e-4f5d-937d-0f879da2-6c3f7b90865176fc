# Year in Review — Spec (v1)

Status: built (phases 0-5). This file is now the design record; the live
reference is `CONTEXT.md` and `docs/DOCUMENTATION.md`. Decisions below come from the planning Q&A on 2026-09-24.
Reviewed against the codebase the same day (codebase-design pass); the fixes are
folded into the sections below and listed in §12. A second pass (grilling, tickets,
TDD) closed the gaps in §13.

A yearly recap of the Completed Library, like the "Wrapped" recaps other apps
do. It reads data the app already has; it never calls IGDB, never reads the
Excel workbook directly, and never writes to `completed_games` or `releases`.

---

## 1. Goal

Open **Year in Review** from the top bar, pick a year, and move through
chapters that sum up the games finished that year: headline numbers, taste,
ratings and personality cards, timing and habits, and a Game of the Year finale
with its theme music.

### Decisions (from the Q&A)

| Question | Decision |
|---|---|
| Content | Numbers & taste, Ratings & personality, Timing & habits. **Not** the Upcoming links (hype check, next year's watchlist). |
| Layout | Sub-tabs, one chapter at a time. Each chapter scrolls vertically inside; changing tab slides horizontally. |
| Flow | Scrolling past the bottom of a chapter carries on into the next tab; scrolling up past the top goes back. Tabs and ←/→ also work. |
| GOTY | Automatic pick (highest rating, ties go to the later finish), with a **Choose my GOTY** override saved per year. |
| Music | A YouTube link you paste for the GOTY theme. Only the video id is stored. |
| Extras | Your note on the GOTY is quoted; **Save as image**; the current year is shown as it builds up ("so far"). |
| Year-only games | Counted in totals, ratings, taste and GOTY; left out of month charts and streaks, with a note saying how many. |
| Placement | A permanent top-bar tab next to Randomizer, with a year picker. |

### Hard rules

- Read-only over completed games. The only new write is the per-year settings
  row (GOTY override and music id).
- No hours played anywhere (they aren't recorded).
- No new npm dependencies. Charts are plain CSS/SVG.
- Trailer rules apply to the music player: store one sanitized YouTube id, use
  `youtube-nocookie.com`, and mount the iframe only after the user clicks
  play.
- Keep the payload light: one summary object per year, with covers as IGDB
  image ids only.

### Non-goals (v1)

- Hours-based cards (marathon, speedrun, total time).
- Links to Upcoming (hype check, next year's watchlist).
- A deep comparison with last year (genre shifts, rating change). The headline
  "+6 on 2025" count is in; the rest is not.
- Music from a local file, or an automatic YouTube search.
- A year-end banner or reminder.
- Randomizer recap.

---

## 2. User flow

1. Top bar: **Year in Review**. It opens the latest year that has finished
   games, or the current year when it already has some.
2. Header: the title "Your 2026 in games", a year picker (every year with at
   least one finished game, plus the current year), and a "so far" badge on the
   current year.
3. Chapter tabs under the header: **Overview · Taste · Ratings · Timing &
   Habits · Game of the Year**. The active tab is underlined; the underline
   slides between tabs.
4. The chapter body scrolls. Cards rise and fade in as they enter view.
5. Scrolling on past the end of a chapter moves to the next tab (see §6.3).
6. Game of the Year is the finale: a full-bleed cover backdrop, the title, your
   rating, your note as a quote, a **▶ Play theme** button, then the
   year-in-covers grid to close.
7. **Save as image** on each chapter saves what is on screen as a PNG.
8. A year with no finished games shows an empty state ("No finished games
   recorded for 2019") and no chapters.

---

## 3. Chapters and cards

"Rated games" means games with a `rating_score`. "Matched" means games with an
`igdb_id`. A card whose data is missing is left out rather than shown empty.
Each chapter ends with a small footnote when it had to leave games out (for
example "4 games have no month and are not in the monthly chart").

### 3.1 Overview

- **Games finished**: the count, and the change against last year ("+6 on
  2025"); the change is left out when last year has no games.
- **Busiest month**: the month with the most finishes, plus a 12-bar month
  chart. Only games with a month.
- **Average rating** over rated games, and how many got 9 or higher.
- **First and last**: the first and last game finished this year, by date.
  Only games with a month or full date; exact dates sort before month-only
  entries in the same month.

### 3.2 Taste

- **Top genres**: the top 5 with percentages ("Your year was 40% RPG").
  A game's genres are its Excel genres plus its IGDB genres, the same rule the
  Completed Library Genre filter uses (`completedGenres`, moved to `shared/` so
  both sides use one definition). Names are compared case-insensitively and a
  game counts once per genre. Percentages are "share of games with that
  genre", so they can add up to more than 100%; the card says "of your games".
- **Top themes**: the top 3 IGDB themes (matched games only), phrased as "a
  strong Horror streak".
- **Platform split** by `user_platform` exactly as entered (the Completed
  Library platform filter matches it the same way), as a percentage bar. An
  empty platform shows as "Unknown platform". Platform spellings are not merged
  ("PS5" and "PlayStation 5" are two platforms), matching the rest of the app.
- **Favourite developer / publisher**: the most frequent one, shown only when
  it appears two or more times ("Three FromSoftware games").
- **Solo or together**: single-player only vs. has multiplayer or co-op, from
  IGDB game modes.
- **Something new**: a genre or platform that appears this year and in no
  earlier year.

### 3.3 Ratings (with personality)

- **Rating spread**: a bar per whole rating from 0 to 10. Ratings can be
  decimals (`9/10` → 9, `95%` → 9.5, `4/5` → 8), so each is rounded half up
  for the chart only; every other card uses the exact value.
- **Hot take**: the game with the largest gap between your rating (×10) and
  the IGDB critic score (`igdb_aggregated_rating`), shown only when the gap is
  at least 15 points ("You gave Starfield 9; critics gave 71").
- **Hidden gem**: your highest-rated game with fewer than 50 IGDB ratings
  (`igdb_total_rating_count`; missing counts as 0) and a rating of 8 or higher.
  Matched games only. The read model does not map this column today; the
  projection in §7 adds it.
- **Critics agreed**: the share of matched, rated games where your rating is
  within 10 points of the critic score.
- **Player type**: one title from the first rule that fits (constants in one
  place so they can be tuned):
  1. **The Critic**: average rating below 6 across 5 or more rated games.
  2. **The Loyalist**: 80% or more of games on one platform (5+ games).
  3. **The Explorer**: 8 or more different genres.
  4. **The Time Traveller**: median release age of 10 or more years.
  5. **The Day-One Hero**: 3 or more day-one finishes.
  6. **The Completionist**: 24 or more games.
  7. Otherwise **The Adventurer**.

  Each title shows its reason ("78% of your games were on PS5").

### 3.4 Timing & Habits

- **Day-one finishes**: games finished within 30 days of their IGDB release
  date. A month-only finish counts when it is in the release month or the one
  after.
- **Late to the party**: the biggest gap between release and finish ("You
  finally beat Half-Life 2, 22 years late"). Shown only when it is 2 years or
  more.
- **Oldest and newest**: the range of release years played.
- **Longest streak**: the most consecutive months with at least one finish.
- **Busiest stretch**: optional; left out of v1 unless it is cheap once the
  streak exists.

### 3.5 Game of the Year (finale)

- The pick: the override when one is saved and that game is still in this
  year, otherwise the automatic pick (highest `rating_score`; ties go to the
  later finish, then the title). With no rated games, the latest finish is
  used and labelled "Your last finish of the year".
- Backdrop: the first IGDB screenshot at `t_1080p`, else the cover at
  `t_cover_big_2x`, blurred behind a sharp cover.
- **Your note**: `notes` quoted in full when present.
- **Choose my GOTY**: a picker listing the year's games (cover, title,
  rating). "Use automatic pick" clears the override.
- **Theme music**: "Set theme music" takes a YouTube link or id. Accepted
  forms: `youtube.com/watch?v=…`, `youtu.be/…`, `youtube.com/embed/…`,
  `youtube.com/shorts/…`, `music.youtube.com/watch?v=…` and a bare 11-character
  id. Only the id is saved; "Remove" clears it.
- **▶ Play theme** mounts a small visible `youtube-nocookie` player (about
  320×180, docked bottom-right). Once started it keeps playing when you switch
  chapters, and it is unmounted when you leave Year in Review or change year.
  The click satisfies the browser's autoplay rule.
- **Year in covers** closes the chapter: every game of the year, in finish
  order, as a cover grid (games with only a year at the end). Covers use
  `srcset` with `t_cover_big` and `t_cover_big_2x`.

---

## 4. Calculation rules

- **Which games**: rows in `completed_games` with `completion_year = Y`, any
  precision.
- **Month**: from `completion_month` (`YYYY-MM`). Year-only rows have none.
- **Release date**: `igdb_release_date` (matched games only).
- **Ratings**: `rating_score` is 0–10. Critic scores are 0–100.
- **Earlier years** (for "Something new" and the "+N on last year" delta): the
  genre and platform sets of all rows with `completion_year < Y`.
- **Years list**: distinct `completion_year` values with at least one game,
  newest first, plus the current year. The current year is
  `inProgress: true`.
- **Finish order** is one function, `finishSortKey`, used by First/Last, the
  covers grid, the GOTY tie-break and the finish label: exact date, then
  month-only entries (sorted as the last day of that month, so an exact date
  in the same month comes first), then year-only entries, then title.
- **Each row is one finish.** The same game finished on two platforms is two
  rows and counts twice, as it does in the library.
- **"Today"** is passed in (`today: Date`), never read inside the calculation.
  The backend passes the local date, which decides the current year and
  `inProgress`.
- All of it is one pure function, `buildYearInReview(input)`, from rows to
  summary (§7), so it can be tested without a database.

---

## 5. Data model — migration v17

```sql
create table year_in_review_settings (
  year integer primary key,
  goty_completed_id text references completed_games(id) on delete set null,
  music_video_id text,
  updated_at text not null default current_timestamp
);
```

- Completed game ids never change after creation, so the override survives
  renames.
- An override pointing at a game that is no longer in that year (deleted, or
  its date was edited) is ignored when reading; the automatic pick is used.
- `music_video_id` is checked against `^[A-Za-z0-9_-]{11}$` before saving.
- `foreign_keys = ON` is already set in `database/db.ts`, so `on delete set
  null` works when a completed game is deleted.
- Like every migration, v17 is backed up first, and an older EXE will refuse
  the upgraded library ("saved by a newer version"). Install the new EXE before
  opening the library with it; there is no downgrade path.

---

## 6. Frontend

### 6.1 Modules

- `apps/frontend/src/useYearInReviewWorkflow.ts`: year list, the selected
  year, loading the summary, the active chapter, and saving the GOTY override
  and music id.
- `apps/frontend/src/yearInReviewNavigation.ts`: a pure module for chapter
  order and the "carry on scrolling" state machine (§6.3), so it can be tested
  without a DOM.
- `apps/frontend/src/views/YearInReviewView.tsx`: header, year picker, tab
  bar, chapter stage and transitions.
- `apps/frontend/src/views/yearInReview/*Chapter.tsx`: one file per chapter,
  plus small shared pieces (`StatCard`, `BarRow`, `PercentBar`).
- `apps/frontend/src/views/yearInReview/ThemePlayer.tsx`: the mini-player.
  It is rendered by `YearInReviewView`, **not** by the GOTY chapter, because
  only the active chapter is mounted and the music must survive chapter
  changes.
- `apps/frontend/src/youtube.ts` (new, extracted): `youtubeEmbedSrc` and
  `youtubePosterSrc`, moved out of `ReleaseMediaGallery.tsx` (today they are
  private there). The trailer gallery and the theme player both use them, so
  there is one place that knows the embed URL, `origin` parameter and
  `youtube-nocookie` host.
- `shared/youtubeLink.ts` (new): `parseYoutubeLink(text) → id | null`. The
  frontend uses it to validate the input as you type; the backend PUT uses it
  again before saving. One parser, two callers.
- Reuse, don't copy: `Backdrop` for the GOTY backdrop, `igdbCoverSrcSet` and
  `screenshotSrc(id, "hero")` from `artwork.ts` for images, and
  `FramedPanel` for cards.
- `api/client.ts`: new `ApiClient` methods (`getYearInReviewYears`,
  `getYearInReview`, `saveYearInReviewSettings`). Add them to
  `tests/frontend/fakeApiClient.ts` in the same change, or the test typecheck
  fails.
- `appShell.ts`: a new view `"year-in-review"`; `App.tsx`: the top-bar tab and
  routing only. The view loads lazily, like the Randomizer.

### 6.2 Layout and motion

- Header and tab bar are fixed; below them one **chapter stage** fills the
  rest of the window. Only the active chapter is mounted, plus the outgoing one
  during a transition.
- Tab change: the outgoing chapter slides out and the incoming one slides in
  from the side of its tab (right when moving forward, left when going back),
  320 ms ease-out, with a slight fade. The tab underline slides at the same
  time.
- Cards reveal with an `IntersectionObserver`: rise 12px and fade in, 60 ms
  apart within a row. Cards render **visible by default**; the hidden start
  state is added only once an observer exists. jsdom and `renderToString` have
  no `IntersectionObserver`, so tests and first paint always see the content.
- Numbers count up once on first reveal (600 ms). The final number is what
  renders first; the count-up is decoration on top, so a test or a capture
  never sees "0".
- `prefers-reduced-motion`: no slide or count-up. Chapters swap with a 120 ms
  fade and cards appear without motion.
- Colours come from the active HD-2D palette tokens; no new colours.

### 6.3 Carrying on into the next chapter

- At the bottom of the chapter's scroll area, more downward wheel input
  builds up "pull". Once the pull reaches a threshold (about 160px of wheel
  delta within 600 ms), the next chapter slides in at its top. A thin progress
  hint at the bottom edge ("Keep scrolling for Taste →") fills as the pull
  builds.
- Pulling up at the top goes to the previous chapter and lands at its
  **bottom**.
- A single fling that reaches the end does not jump straight on: the pull only
  counts after the scroll has come to rest at the edge (no scroll movement for
  about 150 ms), so fast scrolling never skips a chapter.
- Keys: ←/→ change chapter. PageDown/Space at the bottom and PageUp at the top
  carry on like the wheel. Home/End jump to the first and last chapter.
- The last chapter shows "That's your 2026" and no further hint.
- **Short chapters**: when a chapter doesn't overflow, it is at the top and
  bottom at once. "At rest" then starts when the chapter finishes sliding in,
  so a wheel down builds pull toward the next chapter and a wheel up toward the
  previous one.
- **Trackpad and mouse momentum**: after a chapter change, all wheel input is
  ignored until the wheel has been quiet for 400 ms. Without this, the tail of
  one fling carries you through several chapters.
- **Where the logic lives**: `yearInReviewNavigation.ts` is a pure reducer,
  `(state, event) → state`, with events `wheel{deltaY, atTop, atBottom, now}`,
  `scrolled{now}`, `settled{now}`, `key{key}` and `tab{index}`. Time is passed
  in, never read. The view only turns DOM events into these and applies the
  result, so every rule above is tested without a DOM or timers.
- **Keys are scoped**: the key listener is active only while Year in Review is
  the current view, and it ignores key presses in `INPUT`, `TEXTAREA`,
  `SELECT` and the GOTY picker, like the Ctrl+A handler in
  `collectionWorkspace.ts`. Otherwise ←/→ in the music-link box would change
  chapter.

### 6.4 Save as image

- A **Save as image** button in the header saves the visible chapter area.
- Desktop: `preload.ts` gains `captureRegion(rect, suggestedName)` and
  `window.d.ts` its type. It calls a new IPC, `capture-region`. The main
  process:
  - answers only a frame showing the app (the same `decideNavigation` check as
    `api-token`);
  - rounds the rectangle to whole pixels and clamps it to the window's content
    size, refusing an empty result;
  - calls `webContents.capturePage(rect)`, shows a save dialog (default name
    `Year in Review 2026 - Overview.png`, `.png` filter only) and writes the
    PNG. No new library.
  - It lives in its own `apps/desktop/src/captureIpc.ts`, registered like
    `wallpaperIpc.ts`, with a desktop test.
- Before capturing, the view adds a `capturing` class that hides the theme
  player and the header buttons and forces every card to its revealed,
  finished state. It waits two animation frames, so the change is painted,
  then captures, then removes the class.
- Browser dev mode (no desktop shell): `captureRegion` is missing, so the
  button is hidden.

---

## 7. Backend

- **Completed games are read through the Completed Library store**, not with
  new SQL. `CODEBASE_MAP.md` says library tables are read only through their
  stores (the Randomizer asks for `ownedIgdbIds` the same way). So
  `completedGameStore` gains one read, backed by the read model:
  - `yearInReviewRows(year)`: `{ games, earlier, years }`. `games` are this
    year's rows as a new `CompletedReviewRow` projection: the list-item fields
    plus `notes`, `igdbReleaseDate`, `igdbDeveloper`, `igdbPublisher`,
    `igdbThemes`, `igdbGameModes`, `igdbAggregatedRating`,
    `igdbTotalRatingCount` and `screenshots`. `earlier` is the genre and
    platform sets and the game count of every year before `year`. `years` is
    the count per `completion_year`.
  - The projection maps `igdb_total_rating_count`, which `rowToDetail` does not
    map today.
- `apps/backend/src/yearInReview/buildYearInReview.ts`: the pure calculation
  and the **only interface** of the recap logic, `buildYearInReview({ year,
  today, games, earlier, settings }) → YearInReviewSummary`. The per-card
  builders are internal; tests go through `buildYearInReview` (the interface is
  the test surface), which keeps cards free to be reshaped.
- `apps/backend/src/yearInReview/thresholds.ts`: every tunable number (hot
  take gap, hidden-gem count, day-one days, late years, player-type rules).
- `apps/backend/src/yearInReview/yearInReviewSettingsStore.ts`: the only
  reader and writer of `year_in_review_settings`. It does not touch
  `completed_games`.
- `apps/backend/src/actions/yearInReviewActions.ts`: gets the rows and
  settings, calls `buildYearInReview`, and for the PUT checks that the game is
  in that year (through `completedGameStore`) and parses the link with
  `parseYoutubeLink`. `routes/yearInReviewRoutes.ts` stays thin; writes go
  through `runWrite`.
- The years route is registered as `/api/year-in-review/years`, and the year
  route validates `:year` as an integer, so the two can't be confused.
- New routes need the per-launch token like every `/api` route. The renderer
  already sends it through `ApiClient`; nothing is added to `PUBLIC_GETS`.
- The CSP needs no change: `frame-src` already allows
  `https://www.youtube-nocookie.com` and `img-src` allows IGDB images.

### API

| Method | Route | Returns |
|---|---|---|
| GET | `/api/year-in-review/years` | `{ years: { year, count, inProgress }[] }` |
| GET | `/api/year-in-review/:year` | `YearInReviewSummary` |
| PUT | `/api/year-in-review/:year/settings` | body `{ gotyCompletedId?: string \| null, musicLink?: string \| null }`; returns the updated summary. 400 for a bad year, a bad music link, or a game not in that year. |

A year outside 1970–2100 returns 400. A valid year with no games returns a
summary with `count: 0`.

### Shared types (`shared/types.ts`)

`YearInReviewSummary` has `year`, `inProgress`, `count`, `previousYearCount`,
`notes` (the footnotes), and one field per chapter holding its cards. Each card
is `null` when it is left out. It also holds `goty` (game, `isOverride`,
`musicVideoId`) and `games` (id, title, coverImageId, ratingScore, finish
label, in finish order) for the covers grid and the GOTY picker.

---

## 8. Testing

- **Summary (pure)**: every card, including left-out cases. Year-only games are
  counted in totals but not in months or streaks. GOTY tie-break and override.
  An override that is no longer in the year is ignored. Each player-type rule
  and its order. Day-one with exact and month-only dates. Hot take threshold.
  Something new against earlier years.
- **Store and routes**: migration v17; the years list; the PUT validates the
  year, the music link forms and the game's year; the override is cleared when
  its game is deleted.
- **Music link parser**: every accepted form; rejects other hosts, playlists
  without `v=`, and bad ids.
- **Navigation (pure)**: tab order; pull builds only at rest at an edge; up at
  the top lands at the previous chapter's bottom; the last chapter doesn't
  advance.
- **View** (through `fakeApiClient`): tab switching; year picker; the empty
  year; the GOTY picker saves; the theme player mounts only after Play and
  unmounts when leaving the view; no iframe before a click.
- **Desktop**: the `capture-region` handler rejects a rectangle outside the
  window and only answers the app's own frame (same guard as `api-token`).
- **Seam checks from the review**: genres use Excel + IGDB (a game with both
  counts once per genre); decimal ratings round only in the spread; finish
  order puts exact dates before month-only entries in the same month;
  `igdbTotalRatingCount` reaches the summary; the view renders full content
  without `IntersectionObserver`; ←/→ typed in the music box doesn't change
  chapter; momentum after a chapter change doesn't advance again; a short
  chapter advances on one pull; the trailer gallery still works after
  `youtube.ts` is extracted.

---

## 9. Phases

Each phase ends green (`npm test`, `npm run typecheck`, `npm run build`) and
is its own commit.

0. **Before starting**: commit the pending sharper-covers change
   (`igdbCoverSrcSet`, 1080p Completed hero), because this feature reuses those
   helpers. Extract `youtube.ts` and move `completedGenres` to `shared/` as
   their own no-behaviour-change commit, with the existing tests green.
1. **Data and summary**: migration v17, the `completedGameStore` read and its
   projection, the settings store, `buildYearInReview` with tests,
   `parseYoutubeLink`, and the routes. No UI.
2. **View shell**: top-bar tab, year picker, chapter tabs, stage transitions,
   carrying on into the next chapter, card reveal and reduced motion. The
   Overview and Taste chapters.
3. **Ratings and Timing & Habits** chapters.
4. **Game of the Year**: the finale, note quote, GOTY picker, the music link
   and the theme player.
5. **Save as image**, docs (`CONTEXT.md`, `DOCUMENTATION.md`,
   `USER_GUIDE.md`, `CODEBASE_MAP.md`, README) and the EXE (WSL
   procedure in `DOCUMENTATION.md`, "Build & Distribution").

---

## 10. CONTEXT.md additions (make when implementing)

- **Year in Review**: the yearly recap of the Completed Library, read-only
  except for its per-year settings.
- **Game of the Year (GOTY)**: the year's headline game; automatic by rating,
  or the user's saved override.
- **Theme music**: a YouTube id saved per year and played on request in the
  GOTY chapter.
- **Player type**: a title from fixed rules over the year's stats.

---

## 11. Defaults I chose (easy to change)

These weren't asked; say if you want them different:

- Chapter order ends on the GOTY, so the big reveal is last.
- Hot take needs a 15-point gap; hidden gem needs fewer than 50 IGDB ratings
  and your rating of 8+; day-one is within 30 days; "late" means 2+ years.
- Once started, the theme music keeps playing across chapters until you leave
  Year in Review.
- Save as image captures what is on screen, not the whole scrolling chapter.

---

## 12. Review: where the plan would have broken

A codebase-design pass on 2026-09-24 checked each planned module and seam
against the code. Every fix is already in the sections above; this is the
record.

| # | Where it would break | Fix (section) |
|---|---|---|
| 1 | A new Year in Review store reading `completed_games` directly breaks the rule that library tables are read only through their stores. | Read through a new `completedGameStore.yearInReviewRows`; the Year in Review store owns only its settings table (§7). |
| 2 | The read model doesn't map `igdb_total_rating_count`, so Hidden gem would always be empty. | A `CompletedReviewRow` projection that maps it (§7, §3.3). |
| 3 | "IGDB genres, else Excel" contradicts the existing Genre filter rule (Excel + IGDB), so the recap and the library would disagree. | Use the shared `completedGenres` rule (§3.2). |
| 4 | Ratings are decimals (`95%` → 9.5), so "a bar per whole rating" has no bucket for them. | Round half up for the chart only (§3.3). |
| 5 | Four cards each needed "finish order" and would each invent one. | One `finishSortKey` (§4). |
| 6 | The theme player inside the GOTY chapter would be unmounted on the first chapter change, cutting the music. | The player is owned by `YearInReviewView` (§6.1). |
| 7 | A second copy of the YouTube embed URL logic would drift from the trailer one (the `origin` parameter, the nocookie host). | Extract `youtube.ts`; one link parser in `shared/` (§6.1). |
| 8 | jsdom and `renderToString` have no `IntersectionObserver`; hidden-until-revealed cards would render empty in tests and on first paint. | Visible by default; final numbers render first (§6.2). |
| 9 | A chapter shorter than the window never "comes to rest at the edge", so it could never carry on. | Rest starts when the chapter finishes sliding in (§6.3). |
| 10 | Trackpad momentum after a chapter change would skip through several chapters. | 400 ms wheel-quiet cooldown after each change (§6.3). |
| 11 | A document-level ←/→ listener would change chapter while typing a music link. | Scope keys to the view and ignore form fields (§6.3). |
| 12 | Timers and the DOM inside the scroll logic make it untestable. | A pure reducer with time passed in (§6.3). |
| 13 | Capturing straight after hiding the player, or mid-reveal, saves the player or half-faded cards; an unchecked rectangle can fail `capturePage`. | A `capturing` class, wait two frames, clamp the rectangle, and the same frame check as `api-token` (§6.4). |
| 14 | Reading "today" inside the calculation makes current-year and "so far" tests depend on the clock. | `today` is an input (§4). |
| 15 | A new `ApiClient` method without the fake breaks `npm run typecheck` on tests. | Update `fakeApiClient.ts` in the same change (§6.1). |
| 16 | Schema v17 makes older EXEs refuse the library. | Expected; documented, install the new EXE first (§5). |
| 17 | This feature needs the uncommitted sharper-covers helpers. | Phase 0 commits them first (§9). |

Checked and fine as planned: the CSP already allows the nocookie frame and
IGDB images; `foreign_keys` is on, so `on delete set null` works; new routes
get the per-launch token through `ApiClient`; the lazy-loaded view follows the
Randomizer pattern.

---

## 13. Second review: gaps closed before building

A grilling / to-tickets / TDD pass on 2026-09-24, before phase 1. Each rule
below was unstated or ambiguous; the choice is now in the code and pinned by a
test in `tests/backend/yearInReview.test.ts`.

| Gap | Decision |
|---|---|
| Busiest month tie | The earlier month wins. |
| Ties in top genres, themes, platforms, developer | More games first, then name A-Z. |
| Genre display name | The first spelling seen (compared case-insensitively). |
| Theme share | Share of matched games, since only they have themes. |
| Favourite developer/publisher source | The IGDB developer when matched, else the one typed in; compared case-insensitively. |
| Solo or together | A game with any multiplayer, co-op, MMO, split-screen or battle-royale mode is "together". Left out when no game has IGDB modes. |
| Something new in the first recorded year | Left out: everything would be "new". The Unknown platform is never new. |
| Hot take tie | The earlier finish. The critic score is rounded for display. |
| Critics agreed with no comparable games | Left out. |
| Player type "release age" | Completion year minus release year, over matched games with a release date; the Time Traveller needs 3 or more of them. |
| Loyalist on an empty platform | Never: an empty platform counts, but can't make a Loyalist. |
| Late to the party for month-only and year-only finishes | Month-only is measured from the 1st of the month; year-only is left out. Whole years, counted like birthdays. |
| Longest streak | Within the year only, shown from 2 months. |
| GOTY tie after "later finish" | Finish order's own last key, the title. |
| Footnotes | The summary returns `coverage` counts (`withMonth`, `rated`, `matched`); each chapter phrases its own footnote from them. |
| Player type phrasing | The backend returns a `key` and a `reason`; the view owns the title text, so wording changes need no backend change. |
| Years list | A light `completionYearCounts` read, not the whole year's rows. |
| Pinning "today" in route tests | `createBackendApp({ today })`, passed only to the Year in Review routes. |
| Who holds the active chapter | The view's chapter stage, keyed by year, so changing year starts at Overview. The workflow holds only data (years, summary, saving). |
| `key` event edges | Key events carry `atTop`/`atBottom` too, since PageDown/Space/PageUp depend on them. |
| Styles | `views/yearInReview/yearInReview.css`, loaded with the lazy view chunk, so boot CSS doesn't grow. |
| What Save as image captures | The whole Year in Review panel (header, tabs and visible chapter), with buttons, the carry-on hint and the player hidden. Saved to the Pictures folder by default. |
| Capture helper | `yearInReviewCapture.ts` holds the class-then-two-frames-then-capture sequence, so it is tested without Electron. |
| Platform spelling in counts (post-merge review) | Platforms are counted exactly as entered (only trimmed) in the split and the Loyalist rule; genres, themes and developers still fold case. |
| Space on a focused button (post-merge review) | Presses the button; Space turns the page only when no button or link has focus. |
| Theme music after changing year (post-merge review) | The play press is forgotten when the year or the saved link changes, so coming back waits for a new click. |
| A settings save that lands after changing year (post-merge review) | Applied only if its year is still the one selected. |

**Phases vs tracer bullets.** Phase 1 is a horizontal backend slice, which the
tickets skill normally avoids. Kept on purpose: `buildYearInReview` is the deep
module every chapter reads, and it is verifiable on its own through the API
tests. Phases 2-4 are vertical (a chapter's view plus its already-tested data).

**Phase 0 note.** The sharper-covers change was already committed
(`471a204`) before this pass.

**Seams under test** (agreed from §8): `buildYearInReview` and `listReviewYears`
(pure), `parseYoutubeLink` (pure), the HTTP routes through `app.inject`, the
navigation reducer (phase 2), the view through `fakeApiClient` (phases 2-4), and
the `capture-region` handler (phase 5).

