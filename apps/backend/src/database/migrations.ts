import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { basename, dirname, extname, join } from "node:path";
import type { TrackerDatabase } from "./db";
import { createReleaseStore, releaseFtsValues } from "./releaseStore";
import { parseCompletionDate } from "../completed/completedDate";
import { parseRating } from "../completed/completedRating";

const migrations: Array<(db: TrackerDatabase) => void> = [
  migrateToV1,
  migrateToV2,
  migrateToV3,
  migrateToV4,
  migrateToV5,
  migrateToV6,
  migrateToV7,
  migrateToV8,
  migrateToV9,
  migrateToV10,
  migrateToV11,
  migrateToV12,
  migrateToV13,
  migrateToV14,
  migrateToV15,
  migrateToV16,
  migrateToV17,
  migrateToV18,
  migrateToV19,
  migrateToV20,
  migrateToV21
];

const LATEST_SCHEMA_VERSION = migrations.length;

export function runMigrations(db: TrackerDatabase) {
  db.exec(`
    create table if not exists schema_version (version integer not null);
    insert into schema_version (version)
      select 0 where not exists (select 1 from schema_version);
  `);

  let current = Number((db.prepare("select version from schema_version").get() as { version: number }).version);
  if (current > LATEST_SCHEMA_VERSION) {
    throw new Error(`This library was saved by a newer version of Game Release Tracker (schema v${current}; this version understands up to v${LATEST_SCHEMA_VERSION}). Update the app to open it; nothing was changed.`);
  }
  if (current > 0 && current < LATEST_SCHEMA_VERSION) backupBeforeMigrating(db, current);
  for (let index = 0; index < LATEST_SCHEMA_VERSION; index += 1) {
    const target = index + 1;
    if (current >= target) continue;
    migrations[index](db);
    db.prepare("update schema_version set version = ?").run(target);
    current = target;
  }
}

const KEEP_BACKUPS = 3;

// A full copy of the library, taken before an existing database is upgraded, in a "backups" folder next
// to it. Only the most recent few are kept.
function backupBeforeMigrating(db: TrackerDatabase, fromVersion: number) {
  if (db.memory || !db.name) return;
  const folder = join(dirname(db.name), "backups");
  mkdirSync(folder, { recursive: true });
  const stem = basename(db.name, extname(db.name));
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  let target = join(folder, `${stem}.v${fromVersion}.${stamp}.db`);
  for (let copy = 2; existsSync(target); copy++) target = join(folder, `${stem}.v${fromVersion}.${stamp}-${copy}.db`);
  db.prepare("vacuum into ?").run(target);

  const backups = readdirSync(folder)
    .filter(name => name.startsWith(`${stem}.v`) && name.endsWith(".db"))
    .map(name => ({ path: join(folder, name), time: statSync(join(folder, name)).mtimeMs }))
    .sort((a, b) => b.time - a.time || b.path.localeCompare(a.path));
  for (const old of backups.slice(KEEP_BACKUPS)) rmSync(old.path, { force: true });
}

function migrateToV1(db: TrackerDatabase) {
  db.exec(`
    create table if not exists releases (
      id text primary key,
      igdb_id integer,
      title text not null,
      normalized_title text not null,
      date_text text not null default 'TBA',
      release_date text,
      date_precision text not null default 'TBA',
      release_window text,
      category text not null default 'Main',
      source_confidence integer not null default 0,
      igdb_url text,
      updated_at integer,
      created_at text not null default current_timestamp
    );

    create table if not exists release_publishers (
      release_id text not null references releases(id) on delete cascade,
      publisher text not null,
      primary key (release_id, publisher)
    );

    create table if not exists release_developers (
      release_id text not null references releases(id) on delete cascade,
      developer text not null,
      primary key (release_id, developer)
    );

    create table if not exists release_platforms (
      release_id text not null references releases(id) on delete cascade,
      platform text not null,
      primary key (release_id, platform)
    );

    create table if not exists release_categories (
      release_id text not null references releases(id) on delete cascade,
      category text not null,
      release_date text,
      primary key (release_id, category)
    );

    create table if not exists sources (
      id integer primary key autoincrement,
      release_id text references releases(id) on delete cascade,
      source_name text not null,
      source_url text not null,
      field text,
      created_at text not null default current_timestamp
    );

    create table if not exists manual_overrides (
      release_id text not null,
      field text not null,
      value text not null,
      source_type text not null,
      source_url text,
      source_name text,
      updated_at text not null default current_timestamp,
      primary key (release_id, field, source_type)
    );

    create table if not exists user_release_state (
      release_id text primary key,
      hidden integer not null default 0,
      released integer not null default 0,
      watched integer not null default 0,
      updated_at text not null default current_timestamp
    );

    create table if not exists settings (
      key text primary key,
      value text,
      encrypted integer not null default 0,
      updated_at text not null default current_timestamp
    );

    create table if not exists sync_runs (
      id integer primary key autoincrement,
      status text not null,
      started_at text not null default current_timestamp,
      finished_at text,
      added integer not null default 0,
      repaired integer not null default 0,
      skipped integer not null default 0,
      failed integer not null default 0,
      message text,
      igdb_updated_since integer
    );

    create table if not exists sync_log (
      id integer primary key autoincrement,
      sync_run_id integer,
      release_id text,
      title text not null,
      action text not null,
      reason text not null,
      created_at text not null default current_timestamp
    );

    create virtual table if not exists releases_fts using fts5(
      title,
      normalized_title,
      publishers,
      developers,
      sources
    );

    create index if not exists idx_releases_date_precision on releases(release_date, date_precision);
    create index if not exists idx_release_publishers_publisher on release_publishers(publisher, release_id);
    create index if not exists idx_release_categories_category_date on release_categories(category, release_date);
    create index if not exists idx_release_platforms_platform on release_platforms(platform, release_id);

    create trigger if not exists releases_ai after insert on releases begin
      insert into releases_fts(rowid, title, normalized_title, publishers, developers, sources)
      values (
        new.rowid,
        new.title,
        new.normalized_title,
        ${releaseFtsValues("new.id")}
      );
    end;

    create trigger if not exists releases_au after update on releases begin
      delete from releases_fts where rowid = old.rowid;
      insert into releases_fts(rowid, title, normalized_title, publishers, developers, sources)
      values (
        new.rowid,
        new.title,
        new.normalized_title,
        ${releaseFtsValues("new.id")}
      );
    end;

    create trigger if not exists releases_ad after delete on releases begin
      delete from releases_fts where rowid = old.rowid;
    end;
  `);

  rebuildFts(db);
}

function rebuildFts(db: TrackerDatabase) {
  db.exec(`
    delete from releases_fts;
    insert into releases_fts(rowid, title, normalized_title, publishers, developers, sources)
    select
      releases.rowid,
      releases.title,
      releases.normalized_title,
      ${releaseFtsValues("releases.id")}
    from releases;
  `);
}

function hasColumn(db: TrackerDatabase, table: string, column: string) {
  return db.prepare(`pragma table_info(${table})`).all().some(row => (row as { name: string }).name === column);
}


function migrateToV2(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    if (!hasColumn(db, "releases", "eligible")) db.exec("alter table releases add column eligible integer not null default 0");
    if (!hasColumn(db, "releases", "eligibility_reason")) db.exec("alter table releases add column eligibility_reason text");
    if (!hasColumn(db, "releases", "archived_at")) db.exec("alter table releases add column archived_at text");
    if (!hasColumn(db, "releases", "effective_sort_date")) db.exec("alter table releases add column effective_sort_date text");

    db.exec(`
      create table if not exists release_artworks (
        release_id text not null references releases(id) on delete cascade,
        image_id text not null,
        source text not null default 'artwork',
        sort_order integer not null default 0,
        primary key (release_id, image_id)
      );

      create index if not exists idx_releases_eligible_sort_title on releases(eligible, effective_sort_date, title);
      create index if not exists idx_release_artworks_release on release_artworks(release_id, sort_order);
    `);

    createReleaseStore(db).refreshAllEligibility();
  });
  tx();
}

function migrateToV3(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    if (!hasColumn(db, "release_artworks", "source")) db.exec("alter table release_artworks add column source text not null default 'artwork'");
    db.exec(`
      create table if not exists publisher_sync_state (
        approved_term text primary key,
        company_ids text not null default '[]',
        company_names text not null default '[]',
        full_sync_completed_at text,
        last_attempted_offset integer not null default 0,
        last_error text,
        updated_at text not null default current_timestamp
      );

      create index if not exists idx_publisher_sync_state_completed on publisher_sync_state(full_sync_completed_at);
    `);
  });
  tx();
}

function migrateToV4(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    db.exec(`
      create table if not exists blocked_releases (
        id text primary key,
        igdb_id integer,
        normalized_title text not null,
        title text not null,
        reason text,
        created_at text not null default current_timestamp
      );

      create index if not exists idx_blocked_releases_igdb on blocked_releases(igdb_id);
      create index if not exists idx_blocked_releases_title on blocked_releases(normalized_title);
    `);
  });
  tx();
}

function migrateToV5(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    if (!hasColumn(db, "release_artworks", "url")) db.exec("alter table release_artworks add column url text");
  });
  tx();
}

function migrateToV6(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    db.exec(`
      create table if not exists completed_games (
        id text primary key,
        title text not null,
        normalized_title text not null,
        user_platform text not null default '',
        identity_key text not null unique,
        developer text,
        publisher text,
        genres_json text not null default '[]',
        platforms_json text not null default '[]',
        rating_raw text,
        rating_score real,
        completion_date text,
        completion_month text,
        completion_year integer,
        completion_precision text not null default 'none',
        notes text,
        extra_json text not null default '{}',
        source_row_hash text not null default '',
        source_type text not null default 'manual',
        missing_from_latest_import integer not null default 0,
        igdb_id integer,
        cover_image_id text,
        igdb_release_date text,
        igdb_developer text,
        igdb_publisher text,
        igdb_genres_json text not null default '[]',
        igdb_platforms_json text not null default '[]',
        summary text,
        screenshots_json text not null default '[]',
        match_status text not null default 'unmatched',
        last_synced_at text,
        created_at text not null default current_timestamp,
        updated_at text not null default current_timestamp
      );

      create table if not exists completed_match_overrides (
        identity_key text primary key,
        normalized_title text not null,
        user_platform text not null default '',
        igdb_id integer not null,
        updated_at text not null default current_timestamp
      );

      create table if not exists completed_library_sync_state (
        id integer primary key check (id = 1),
        file_name text,
        status text not null default 'idle',
        added integer not null default 0,
        updated integer not null default 0,
        matched integer not null default 0,
        needs_review integer not null default 0,
        missing integer not null default 0,
        skipped integer not null default 0,
        failed integer not null default 0,
        warnings_json text not null default '[]',
        message text,
        last_synced_at text
      );

      insert or ignore into completed_library_sync_state (id) values (1);

      create index if not exists idx_completed_games_identity on completed_games(identity_key);
      create index if not exists idx_completed_games_title_platform on completed_games(normalized_title, user_platform);
      create index if not exists idx_completed_games_completion on completed_games(completion_year, completion_month);
      create index if not exists idx_completed_games_rating on completed_games(rating_score);
      create index if not exists idx_completed_games_match on completed_games(match_status);
      create index if not exists idx_completed_games_missing on completed_games(missing_from_latest_import);
    `);
  });
  tx();
}

function migrateToV7(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    db.exec(`
      create table if not exists release_screenshots (
        release_id text not null references releases(id) on delete cascade,
        image_id text not null,
        source text not null default 'artwork',
        sort_order integer not null default 0,
        primary key (release_id, image_id)
      );

      create index if not exists idx_release_screenshots_release on release_screenshots(release_id, sort_order);
    `);
  });
  tx();
}

function migrateToV8(_db: TrackerDatabase) {
  // Keep the version number monotonic after retiring an experimental migration.
}

function migrateToV9(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    db.exec(`
      create table if not exists release_trailers (
        release_id text not null references releases(id) on delete cascade,
        video_id text not null,
        name text,
        provider text not null default 'youtube',
        sort_order integer not null default 0,
        primary key (release_id, video_id)
      );

      create index if not exists idx_release_trailers_release on release_trailers(release_id, sort_order);
    `);
  });
  tx();
}

function migrateToV10(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    if (!hasColumn(db, "completed_games", "hours_played")) db.exec("alter table completed_games add column hours_played real");
    if (!hasColumn(db, "completed_games", "igdb_themes_json")) db.exec("alter table completed_games add column igdb_themes_json text not null default '[]'");
    if (!hasColumn(db, "completed_games", "igdb_game_modes_json")) db.exec("alter table completed_games add column igdb_game_modes_json text not null default '[]'");
    if (!hasColumn(db, "completed_games", "igdb_rating")) db.exec("alter table completed_games add column igdb_rating real");
    if (!hasColumn(db, "completed_games", "igdb_aggregated_rating")) db.exec("alter table completed_games add column igdb_aggregated_rating real");
    if (!hasColumn(db, "completed_games", "igdb_total_rating")) db.exec("alter table completed_games add column igdb_total_rating real");
    if (!hasColumn(db, "completed_games", "igdb_total_rating_count")) db.exec("alter table completed_games add column igdb_total_rating_count integer");
  });
  tx();
}

function migrateToV11(db: TrackerDatabase) {
  db.exec(`
    create table if not exists release_genres (
      release_id text not null references releases(id) on delete cascade,
      genre text not null,
      primary key (release_id, genre)
    );

    create index if not exists idx_release_genres_genre on release_genres(genre, release_id);
  `);
}

// Remember which Excel row a completed game came from, so a rename or platform change made in the app survives the next Excel sync.
function migrateToV12(db: TrackerDatabase) {
  const tx = db.transaction(() => {
    if (!hasColumn(db, "completed_games", "source_identity_key")) db.exec("alter table completed_games add column source_identity_key text");
    db.exec(`
      update completed_games set source_identity_key = identity_key where source_type = 'excel' and source_identity_key is null;
      create index if not exists idx_completed_games_source_identity on completed_games(source_identity_key);
    `);
  });
  tx();
}

// One Release per IGDB game. Skipped if an older database already holds duplicates, so startup never fails.
function migrateToV13(db: TrackerDatabase) {
  const duplicate = db.prepare("select 1 from releases where igdb_id is not null group by igdb_id having count(*) > 1 limit 1").get();
  if (!duplicate) db.exec("create unique index if not exists idx_releases_igdb_id_unique on releases(igdb_id) where igdb_id is not null");
}

// Drop the unused backlog, game-length and pick-history tables v10 created for a backlog randomizer that was never built.
function migrateToV14(db: TrackerDatabase) {
  db.exec(`
    drop table if exists backlog_games;
    drop table if exists backlog_match_overrides;
    drop table if exists backlog_library_sync_state;
    drop table if exists game_lengths;
    drop table if exists game_length_overrides;
    drop table if exists randomizer_picks;
  `);
}

// Randomizer pick history. Recent picks form the cooldown window that keeps spins from repeating.
function migrateToV15(db: TrackerDatabase) {
  db.exec(`
    create table if not exists randomizer_picks (
      id integer primary key autoincrement,
      igdb_id integer not null,
      title text not null,
      cover_image_id text,
      filters_json text not null default '{}',
      picked_at text not null default current_timestamp
    );
    create index if not exists idx_randomizer_picks_recent on randomizer_picks(picked_at desc);
  `);
}

// One-time repairs that used to run on every launch. Every write path now keeps eligibility and completion
// dates current, so they only fix rows written by older versions. A future eligibility policy change
// should add a migration that calls refreshAllEligibility again.
function migrateToV16(db: TrackerDatabase) {
  db.transaction(() => {
    createReleaseStore(db).refreshAllEligibility();
    backfillCompletedGameDates(db);
  })();
}

// Year in Review settings, one row per year: the Game of the Year override and the theme music's YouTube id.
// Deleting the chosen completed game clears the override (foreign keys are on in db.ts).
function migrateToV17(db: TrackerDatabase) {
  db.exec(`
    create table if not exists year_in_review_settings (
      year integer primary key,
      goty_completed_id text references completed_games(id) on delete set null,
      music_video_id text,
      updated_at text not null default current_timestamp
    );
  `);
}

// v18 retires the Excel import: the app's database is the Completed Library now. Clears the "missing from the
// latest Excel import" flags and drops the sync status table (the columns stay, so old libraries keep their data).
// Games added or re-rated in the app before v18 saved the rating text without its score, so cards, charts and
// filters treated them as unrated; this fills the score from the text where it is missing.
function migrateToV18(db: TrackerDatabase) {
  db.exec(`
    update completed_games set missing_from_latest_import = 0 where missing_from_latest_import != 0;
    drop table if exists completed_library_sync_state;
  `);
  const rows = db.prepare("select id, rating_raw ratingRaw from completed_games where rating_score is null and coalesce(rating_raw, '') != ''").all() as Array<{ id: string; ratingRaw: string }>;
  const update = db.prepare("update completed_games set rating_score = ?, updated_at = current_timestamp where id = ?");
  db.transaction(() => {
    for (const row of rows) {
      const score = parseRating(row.ratingRaw);
      if (score !== null) update.run(score, row.id);
    }
  })();
}

// The release store refreshes FTS after it has saved the release and all child rows.
function migrateToV19(db: TrackerDatabase) {
  db.exec(`
    create index if not exists idx_sources_release_id on sources(release_id);
    drop trigger if exists releases_ai;
    drop trigger if exists releases_au;
  `);
}

function backfillCompletedGameDates(db: TrackerDatabase) {
  const rows = db.prepare(`
    select id, completion_date completionDate, completion_month completionMonth, completion_year completionYear, completion_precision completionPrecision
    from completed_games
    where coalesce(completion_date, '') != ''
      and (completion_month is null or completion_month = '' or completion_year is null or completion_precision = 'none')
  `).all() as Array<{
    id: string;
    completionDate: string | null;
    completionMonth: string | null;
    completionYear: number | null;
    completionPrecision: string;
  }>;
  const update = db.prepare(`
    update completed_games
    set completion_date = ?,
        completion_month = ?,
        completion_year = ?,
        completion_precision = ?,
        updated_at = current_timestamp
    where id = ?
  `);
  for (const row of rows) {
    const parsed = parseCompletionDate(row.completionDate);
    if (parsed.completionPrecision === "none") continue;
    update.run(parsed.completionDate, parsed.completionMonth, parsed.completionYear, parsed.completionPrecision, row.id);
  }
}

// v20 makes the sync policy the user's own: the tracked publishers are a table the Settings page edits
// (by IGDB company id), which replaces the built-in publisher list and its name-lookup cache. Companies
// that cache had already found become tracked publishers, so an existing library keeps syncing the same
// games. Stored eligibility no longer includes a fixed earliest date (the list applies the user's "track
// from" date), so it is recomputed once.
function migrateToV20(db: TrackerDatabase) {
  db.exec(`
    create table if not exists tracked_publishers (
      company_id integer primary key,
      name text not null,
      added_at text not null default current_timestamp
    );
  `);
  const hasLookupCache = db.prepare("select 1 from sqlite_master where type = 'table' and name = 'publisher_sync_state'").get();
  if (hasLookupCache) {
    db.exec(`
      insert or ignore into tracked_publishers (company_id, name)
        select cast(ids.value as integer), coalesce(json_extract(lookup.company_names, '$[' || ids.key || ']'), lookup.approved_term)
        from publisher_sync_state lookup, json_each(lookup.company_ids) ids;
      drop table publisher_sync_state;
    `);
  }
  createReleaseStore(db).refreshAllEligibility();
}

// v21 keeps a release's date history: each date change a sync brings in (delayed, announced, moved up),
// for the "Delayed from" badge, the detail page's history and release alerts, and which alerts were
// already shown (release_alerts_sent), so each is shown once. Deleting a release deletes both.
function migrateToV21(db: TrackerDatabase) {
  db.exec(`
    create table if not exists release_date_changes (
      id integer primary key autoincrement,
      release_id text not null references releases(id) on delete cascade,
      kind text not null,
      from_text text not null,
      to_text text not null,
      from_sort_date text,
      to_sort_date text,
      sync_run_id integer,
      changed_at text not null default current_timestamp
    );
    create index if not exists idx_release_date_changes_release on release_date_changes(release_id, id);
    create table if not exists release_alerts_sent (
      release_id text not null references releases(id) on delete cascade,
      alert_key text not null,
      sent_at text not null default current_timestamp,
      primary key (release_id, alert_key)
    );
  `);
}
