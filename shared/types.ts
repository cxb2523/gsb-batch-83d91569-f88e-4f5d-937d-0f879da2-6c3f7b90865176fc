export type ReleaseCategory =
  | "Main"
  | "DLC"
  | "Expansion"
  | "Standalone Expansion"
  | "Remake"
  | "Remaster"
  | "Expanded Game"
  | "Port";

export type DatePrecision = "Exact" | "Month" | "Window" | "Year" | "TBA";

// How a sync changed a release's date: pushed later, set more exactly within the old period, or moved up.
export type DateChangeKind = "delayed" | "announced" | "earlier";

// A system notification about a watched game, handed to the desktop app once.
export interface ReleaseAlert {
  releaseId: string;
  kind: "out" | DateChangeKind;
  title: string;
  body: string;
}

export interface ReleaseDateChange {
  kind: DateChangeKind;
  fromText: string;
  toText: string;
  changedAt: string;
}
export type SyncRunStatus = "idle" | "running" | "success" | "partial" | "failed";
export type OverrideSourceType = "igdb" | "seeded" | "user";

export interface IgdbCompanyRef {
  company?: { id?: number; name?: string };
  developer?: boolean;
  publisher?: boolean;
}

export interface IgdbPlatformRef {
  id?: number;
  abbreviation?: string;
  name?: string;
  slug?: string;
}

export interface IgdbReleaseDateRef {
  human?: string;
  date?: number;
  y?: number;
  m?: number;
  d?: number;
  date_format?: number;
  platform?: IgdbPlatformRef;
}

export interface IgdbGameLike {
  id: number;
  name: string;
  slug?: string;
  url?: string;
  summary?: string;
  game_type?: number;
  first_release_date?: number;
  release_dates?: IgdbReleaseDateRef[];
  platforms?: IgdbPlatformRef[];
  genres?: { name?: string }[];
  themes?: { name?: string }[];
  game_modes?: { name?: string }[];
  involved_companies?: IgdbCompanyRef[];
  hypes?: number;
  rating?: number;
  rating_count?: number;
  aggregated_rating?: number;
  total_rating?: number;
  total_rating_count?: number;
  updated_at?: number;
  cover?: { image_id?: string };
  artworks?: { image_id?: string }[];
  screenshots?: { image_id?: string }[];
  videos?: { video_id?: string; name?: string }[];
}

export interface ReleaseDateChoice {
  dateText: string;
  releaseDate: string | null;
  datePrecision: DatePrecision;
  releaseWindow: string | null;
  sourceConfidence: number;
}

export interface ReleaseArtwork {
  imageId: string;
  source?: "artwork" | "cover" | "local" | "steamgriddb";
  url?: string;
}

export interface GameTrailer {
  videoId: string;
  name?: string | null;
  provider: "youtube";
}

export interface ReleaseEligibility {
  eligible: boolean;
  eligibilityReason: string | null;
  effectiveSortDate: string | null;
}

export interface NormalizedRelease extends ReleaseDateChoice, ReleaseEligibility {
  id: string;
  igdbId?: number;
  title: string;
  normalizedTitle: string;
  category: ReleaseCategory;
  publishers: string[];
  developers: string[];
  platforms: string[];
  genres: string[];
  igdbUrl?: string;
  sourceUrls?: string[];
  updatedAt?: number;
  artworks: ReleaseArtwork[];
  screenshots: ReleaseArtwork[];
  trailers: GameTrailer[];
}

export interface ReleaseOverride {
  field: string;
  value: string;
  sourceType: OverrideSourceType;
  sourceUrl?: string;
  sourceName?: string;
  updatedAt?: string;
}

export interface ReleaseListItem {
  id: string;
  title: string;
  dateText: string;
  releaseDate?: string | null;
  datePrecision: DatePrecision;
  releaseWindow?: string | null;
  effectiveSortDate?: string | null;
  category: ReleaseCategory;
  publishers: string[];
  developers: string[];
  platforms: string[];
  genres: string[];
  sourceConfidence: number;
  artworks: ReleaseArtwork[];
  eligible?: boolean;
  hidden?: boolean;
  watched?: boolean;
  released?: boolean;
  // The newest delay or move up a sync recorded, if any (an announced date shows only in the detail).
  lastDateChange?: ReleaseDateChange | null;
}

export interface ReleaseDetail extends ReleaseListItem {
  // Every recorded date change, newest first.
  dateChanges?: ReleaseDateChange[];
  igdbUrl?: string | null;
  sources: Array<{ sourceName: string; sourceUrl: string; field?: string | null }>;
  eligibilityReason?: string | null;
  screenshots: ReleaseArtwork[];
  trailers: GameTrailer[];
}

export interface ManualReleaseCandidate {
  igdbId: number;
  title: string;
  publishers: string[];
  developers: string[];
  platforms: string[];
  category: ReleaseCategory;
  dateText: string;
  datePrecision: DatePrecision;
  releaseDate: string | null;
  releaseWindow: string | null;
  sourceUrl?: string | null;
  coverImageId?: string | null;
  artworks: ReleaseArtwork[];
  screenshots: ReleaseArtwork[];
  trailers: GameTrailer[];
}

export interface ReleaseListResponse {
  items: ReleaseListItem[];
  truncated: boolean;
  total: number;
}

export interface SyncStatus {
  status: SyncRunStatus;
  added: number;
  repaired: number;
  skipped: number;
  failed: number;
  lastSuccessfulSyncAt?: string | null;
  message?: string;
}

// The four platform families the user can track; each maps to IGDB platforms in PLATFORM_FAMILIES.
export type PlatformFamily = "pc" | "xbox" | "playstation" | "switch";

// A publisher or studio the user tracks, by IGDB company id.
export interface TrackedPublisher {
  id: number;
  name: string;
}

// What the IGDB sync looks for. A new library tracks no publishers, every platform family, releases from
// the start of the current year, and syncs only when the user asks.
export interface SyncSettings {
  publishers: TrackedPublisher[];
  platforms: PlatformFamily[];
  trackFrom: string;
  autoSync: boolean;
  // Desktop notifications about watched games (on unless turned off).
  alerts: boolean;
}

export type SyncSettingsPatch = Partial<Pick<SyncSettings, "platforms" | "trackFrom" | "autoSync" | "alerts">>;

export interface SettingsStatus {
  credentialStatus: { status: string; message?: string };
  autoSyncDue: boolean;
  credentials: {
    IGDB_CLIENT_ID: SavedCredential;
    IGDB_CLIENT_SECRET: SavedCredential;
    IGDB_ACCESS_TOKEN: SavedCredential;
    STEAMGRIDDB_API_KEY: SavedCredential;
  };
}

// Unreadable: a value is stored but its encryption key was lost, so it has to be entered again.
export interface SavedCredential {
  saved: boolean;
  unreadable?: boolean;
}

export type CompletedDatePrecision = "exact" | "month" | "year" | "none";
export type CompletedMatchStatus = "unmatched" | "matched" | "needsReview";
export type CompletedViewMode = "grouped" | "grid";

export interface CompletedGameListItem {
  id: string;
  title: string;
  normalizedTitle: string;
  userPlatform: string;
  ratingRaw?: string | null;
  ratingScore?: number | null;
  completionDate?: string | null;
  completionMonth?: string | null;
  completionYear?: number | null;
  completionPrecision: CompletedDatePrecision;
  developer?: string | null;
  publisher?: string | null;
  genres: string[];
  igdbGenres: string[];
  platforms: string[];
  coverImageId?: string | null;
  igdbId?: number | null;
  matchStatus: CompletedMatchStatus;
}

export interface CompletedGameDetail extends CompletedGameListItem {
  notes?: string | null;
  extra: Record<string, string>;
  igdbReleaseDate?: string | null;
  igdbDeveloper?: string | null;
  igdbPublisher?: string | null;
  igdbPlatforms: string[];
  igdbThemes: string[];
  igdbGameModes: string[];
  igdbRating?: number | null;
  igdbAggregatedRating?: number | null;
  igdbTotalRating?: number | null;
  summary?: string | null;
  screenshots: ReleaseArtwork[];
  lastSyncedAt?: string | null;
}

export interface CompletedGameFilters {
  search?: string;
  platform?: string;
  year?: string;
  month?: string;
  rating?: string;
  dateState?: "" | "dated" | "undated";
}

export interface CompletedGameListResponse {
  items: CompletedGameListItem[];
  total: number;
}

export interface CompletedGameMatchCandidate {
  igdbId: number;
  title: string;
  releaseDate?: string | null;
  platforms: string[];
  summary?: string | null;
  coverImageId?: string | null;
  confidence: number;
}

export interface RandomizerOption {
  id: number;
  name: string;
}

export type RandomizerPlatformFamily = "PlayStation" | "Xbox" | "Nintendo" | "PC";

export interface RandomizerPlatformOption extends RandomizerOption {
  family: RandomizerPlatformFamily;
}

export interface RandomizerOptions {
  genres: RandomizerOption[];
  themes: RandomizerOption[];
  gameModes: RandomizerOption[];
  perspectives: RandomizerOption[];
  // The mainstream platforms the Randomizer is limited to.
  platforms: RandomizerPlatformOption[];
  // Popular IGDB keywords; any other keyword can be found with the tag search.
  tags: RandomizerOption[];
  // Spins draw from the sample library's games, not IGDB (no IGDB keys saved yet).
  sample?: boolean;
}

// Quick toggles that stand for a group of IGDB keywords.
export type RandomizerPreset = "jrpg" | "anime";

// IGDB has two kinds of series: broad franchises ("Final Fantasy") and tighter collections
// ("Final Fantasy Crystal Chronicles"). The series filter matches either.
export interface RandomizerSeriesOption extends RandomizerOption {
  kind: "franchise" | "collection";
}

// A game found by name, used as the seed for "similar to".
export interface RandomizerGameOption extends RandomizerOption {
  year?: number | null;
  coverImageId?: string | null;
}

// Every filter is optional; ids are IGDB ids. Multi-selects mean "any of" except tags, which mean "all of".
export interface RandomizerFilters {
  genreIds?: number[];
  excludeGenreIds?: number[];
  themeIds?: number[];
  excludeThemeIds?: number[];
  gameModeIds?: number[];
  perspectiveIds?: number[];
  // Empty means every mainstream platform.
  platformIds?: number[];
  tagIds?: number[];
  excludeTagIds?: number[];
  presets?: RandomizerPreset[];
  // Developed by a studio based in Japan.
  madeInJapan?: boolean;
  // Series: a game in any chosen franchise or collection.
  franchiseIds?: number[];
  collectionIds?: number[];
  // Only games IGDB lists as similar to this game (widened one step when those run out).
  similarToId?: number;
  // Display only; never reaches an IGDB query.
  similarToTitle?: string;
  // Also allow games with no IGDB rating yet, whatever the rating filters say.
  includeUnrated?: boolean;
  minRating?: number;
  maxRating?: number;
  minRatingCount?: number;
  maxRatingCount?: number;
  releasedFromYear?: number;
  releasedToYear?: number;
  includeRemakes?: boolean;
  hideCompleted?: boolean;
  hideUpcoming?: boolean;
}

export interface RandomizerPick {
  igdbId: number;
  title: string;
  url?: string | null;
  coverImageId?: string | null;
  releaseYear?: number | null;
  genres: string[];
  themes: string[];
  gameModes: string[];
  platforms: string[];
  totalRating?: number | null;
  totalRatingCount?: number | null;
  summary?: string | null;
}

export interface RandomizerReelItem {
  title: string;
  coverImageId?: string | null;
}

export interface RandomizerSpinResponse {
  pick: RandomizerPick | null;
  reels: RandomizerReelItem[];
  poolSize: number;
  repeatAllowed: boolean;
  // A "similar to" spin ran out of direct matches and used games similar to those.
  similarWidened?: boolean;
  reason?: string;
}

export interface RandomizerHistoryItem {
  id: number;
  igdbId: number;
  title: string;
  coverImageId?: string | null;
  pickedAt: string;
}

// Year in Review: the yearly recap of the Completed Library. Every card is null when its data is missing.
export interface YearInReviewYear {
  year: number;
  count: number;
  inProgress: boolean;
}

export interface YearInReviewGame {
  id: string;
  title: string;
  coverImageId: string | null;
  ratingScore: number | null;
  userPlatform: string;
  finishLabel: string;
  // Finish month 1..12; null for year-only finishes.
  month: number | null;
}

export interface YearInReviewShare {
  name: string;
  count: number;
  // The games counted, so a chapter can list them.
  ids: string[];
  // count / games considered, 0..1. Genre shares can add up to more than 1.
  share: number;
}

export interface YearInReviewSummary {
  year: number;
  inProgress: boolean;
  count: number;
  previousYearCount: number | null;
  // How many of the year's games each kind of card could use; the chapters phrase their footnotes from these.
  coverage: { withMonth: number; rated: number; matched: number };
  overview: {
    // Finishes per month, January first. Only games with a month.
    months: number[];
    busiestMonth: { month: number; count: number } | null;
    averageRating: number | null;
    nineOrHigher: number;
    first: YearInReviewGame | null;
    last: YearInReviewGame | null;
  };
  taste: {
    genres: YearInReviewShare[];
    themes: YearInReviewShare[];
    platforms: YearInReviewShare[];
    developer: { name: string; count: number } | null;
    publisher: { name: string; count: number } | null;
    playModes: { solo: number; together: number } | null;
    somethingNew: { genres: string[]; platforms: string[] } | null;
  };
  ratings: {
    // Games per whole rating 0..10 (rounded half up); null without rated games.
    spread: number[] | null;
    hotTake: { game: YearInReviewGame; rating: number; criticScore: number } | null;
    hiddenGem: { game: YearInReviewGame; ratingCount: number } | null;
    criticsAgreed: { agreed: number; total: number } | null;
    playerType: { key: YearInReviewPlayerType; reason: string } | null;
  };
  timing: {
    dayOne: { games: YearInReviewGame[] } | null;
    lateToTheParty: { game: YearInReviewGame; years: number; releaseYear: number } | null;
    releaseRange: { oldest: { game: YearInReviewGame; year: number }; newest: { game: YearInReviewGame; year: number } } | null;
    longestStreak: { months: number; from: number; to: number } | null;
  };
  goty: {
    game: YearInReviewGame;
    isOverride: boolean;
    // No rated games: the pick is the year's last finish.
    isLatestFinish: boolean;
    note: string | null;
    backdrop: { imageId: string; kind: "screenshot" | "cover" } | null;
    musicVideoId: string | null;
  } | null;
  // Every game of the year in finish order (year-only finishes last).
  games: YearInReviewGame[];
}

export type YearInReviewPlayerType = "critic" | "loyalist" | "explorer" | "time-traveller" | "day-one-hero" | "completionist" | "adventurer";

export interface YearInReviewSettingsPatch {
  // Absent: unchanged. null: cleared.
  gotyCompletedId?: string | null;
  musicLink?: string | null;
}
