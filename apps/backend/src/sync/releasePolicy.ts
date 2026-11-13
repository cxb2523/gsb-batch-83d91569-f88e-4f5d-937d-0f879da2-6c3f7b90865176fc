import { ACCEPTED_GAME_TYPES, ALL_PLATFORM_FAMILIES, EXCLUDED_TITLE_TERMS, GAME_TYPE_LABELS, PLATFORM_FAMILIES } from "../../../../shared/constants";
import type { DatePrecision, IgdbGameLike, IgdbPlatformRef, NormalizedRelease, PlatformFamily, ReleaseDateChoice, ReleaseEligibility } from "../../../../shared/types";
import { getCompanyNames, getPlatformNames, pickTrailer, unixToIso, unixToText } from "../igdb/igdbGame";
import { normalizeText } from "../text/normalizeText";

// The Upcoming release policy: which IGDB games qualify, which release date counts, when a Release is
// eligible for Upcoming, and how an IGDB game becomes a Release.

// What the user's sync settings decide: the tracked companies, the platform families and the earliest
// release date.
export interface ReleasePolicyRules {
  publisherIds: readonly number[];
  platforms: readonly PlatformFamily[];
  trackFrom: string;
}

export function createReleasePolicy(rules: ReleasePolicyRules) {
  const tracked = new Set(rules.publisherIds);
  return {
    evaluate(game: IgdbGameLike) {
      const reasons: string[] = [];
      const title = game.name ?? "";
      const gameType = game.game_type ?? 0;
      const eligibility = computeSortDateAndEligibility(chooseBestReleaseDate(game, rules.platforms));

      if (!ACCEPTED_GAME_TYPES.includes(gameType as (typeof ACCEPTED_GAME_TYPES)[number])) reasons.push(`unsupported game_type ${gameType}`);
      if (EXCLUDED_TITLE_TERMS.some(term => title.toLowerCase().includes(term.toLowerCase()))) reasons.push("excluded title phrase");
      if (!onPlatforms(game.platforms, rules.platforms)) reasons.push("not on a tracked platform");
      if (!publisherOrDeveloperIds(game).some(id => tracked.has(id))) reasons.push("not by a tracked publisher");
      if (!eligibility.eligible) reasons.push(eligibility.eligibilityReason ?? "ineligible release date");
      else if (eligibility.effectiveSortDate! < rules.trackFrom) reasons.push(`before ${rules.trackFrom}`);

      return { accepted: reasons.length === 0, reasons };
    },
    normalize: (game: IgdbGameLike) => normalizeIgdbGame(game, rules.platforms)
  };
}

export type ReleasePolicy = ReturnType<typeof createReleasePolicy>;

function onPlatforms(platforms: IgdbPlatformRef[] = [], families: readonly PlatformFamily[]) {
  return platforms.some(platform => families.some(family => {
    const { ids, slugs } = PLATFORM_FAMILIES[family];
    if (typeof platform.id === "number" && ids.includes(platform.id)) return true;
    return slugs.includes((platform.slug ?? "").toLowerCase());
  }));
}

// Only companies credited as publisher or developer count; IGDB also lists porting and support studios.
function publisherOrDeveloperIds(game: IgdbGameLike) {
  return (game.involved_companies ?? [])
    .filter(involved => involved.publisher || involved.developer)
    .map(involved => involved.company?.id)
    .filter((id): id is number => typeof id === "number");
}

// The earliest date on a tracked platform wins; a date without a platform counts for every platform.
export function chooseBestReleaseDate(game: IgdbGameLike, platforms: readonly PlatformFamily[] = ALL_PLATFORM_FAMILIES): ReleaseDateChoice {
  const acceptedDates = (game.release_dates ?? [])
    .filter(date => !date.platform || onPlatforms([date.platform], platforms))
    .sort((a, b) => (a.date ?? Number.MAX_SAFE_INTEGER) - (b.date ?? Number.MAX_SAFE_INTEGER));

  const candidate = acceptedDates[0] ?? (game.release_dates ?? [])[0];
  if (candidate?.date) {
    const datePrecision = precisionOfDatedHuman(candidate.human);
    return {
      dateText: candidate.human || unixToText(candidate.date),
      releaseDate: unixToIso(candidate.date),
      datePrecision,
      releaseWindow: datePrecision === "Year" || datePrecision === "Window" ? candidate.human! : null,
      sourceConfidence: 90
    };
  }

  if (candidate?.human) {
    const text = candidate.human;
    return {
      dateText: text,
      releaseDate: null,
      datePrecision: /^\d{4}$/.test(text.trim()) ? "Year" : "Window",
      releaseWindow: text,
      sourceConfidence: 60
    };
  }

  if (game.first_release_date) {
    return {
      dateText: unixToText(game.first_release_date),
      releaseDate: unixToIso(game.first_release_date),
      datePrecision: "Exact",
      releaseWindow: null,
      sourceConfidence: 80
    };
  }

  return { dateText: "TBA", releaseDate: null, datePrecision: "TBA", releaseWindow: null, sourceConfidence: 10 };
}

// IGDB dates a vague release at the end of its period ("2027" is Dec 31, 2027), so its human text, not its
// timestamp, says how precise it is. Only a full day counts as Exact and gets a countdown.
// How exact a date's words are: "2027" a Year, "Mar 2027" a Month, "Q4 2027" a Window, else Exact.
export function precisionOfDatedHuman(human: string | undefined): DatePrecision {
  const text = human?.trim() ?? "";
  if (/^\d{4}$/.test(text)) return "Year";
  if (/^[A-Za-z]{3,9}\.? \d{4}$/.test(text) && !/^(spring|summer|fall|autumn|winter|early|late|mid)\b/i.test(text)) return "Month";
  if (/\b(q[1-4]|h[12]|tbd|spring|summer|fall|autumn|winter|early|late|mid)\b/i.test(text)) return "Window";
  return "Exact";
}

// A stored Release is eligible for Upcoming once it has a date to sort by. The user's "track from" date
// is applied when the list is read, so changing it needs no rewrite of stored rows.
export function computeSortDateAndEligibility(date: Pick<ReleaseDateChoice, "dateText" | "releaseDate" | "datePrecision" | "releaseWindow">): ReleaseEligibility {
  const effectiveSortDate = deriveEffectiveSortDate(date);
  if (!effectiveSortDate) return { eligible: false, eligibilityReason: "TBA release date", effectiveSortDate: null };
  return { eligible: true, eligibilityReason: null, effectiveSortDate };
}

function deriveEffectiveSortDate(date: Pick<ReleaseDateChoice, "dateText" | "releaseDate" | "datePrecision" | "releaseWindow">) {
  if (date.releaseDate) return date.releaseDate;
  if (date.datePrecision === "TBA") return null;
  const text = (date.releaseWindow || date.dateText || "").trim();
  const year = text.match(/\b(20\d{2})\b/)?.[1];
  if (!year) return null;
  if (date.datePrecision === "Year" || /^\d{4}$/.test(text)) return `${year}-01-01`;
  const lowered = text.toLowerCase();
  if (lowered.includes("q2") || lowered.includes("spring")) return `${year}-04-01`;
  if (lowered.includes("q3") || lowered.includes("summer")) return `${year}-07-01`;
  if (lowered.includes("q4") || lowered.includes("fall") || lowered.includes("autumn") || lowered.includes("late")) return `${year}-10-01`;
  return `${year}-01-01`;
}

export function normalizeIgdbGame(game: IgdbGameLike, platforms: readonly PlatformFamily[] = ALL_PLATFORM_FAMILIES): NormalizedRelease {
  const date = chooseBestReleaseDate(game, platforms);
  const eligibility = computeSortDateAndEligibility(date);
  const publishers = getCompanyNames(game, "publisher");
  const developers = getCompanyNames(game, "developer");
  const artworkIds = (game.artworks ?? []).map(art => art.image_id).filter((imageId): imageId is string => Boolean(imageId));
  const artworks: NormalizedRelease["artworks"] = artworkIds.map(imageId => ({ imageId, source: "artwork" as const }));
  if (game.cover?.image_id && !artworkIds.includes(game.cover.image_id)) {
    artworks.push({ imageId: game.cover.image_id, source: "cover" as const });
  }
  const screenshots: NormalizedRelease["screenshots"] = (game.screenshots ?? [])
    .map(screen => screen.image_id)
    .filter((imageId): imageId is string => Boolean(imageId))
    .slice(0, 6)
    .map(imageId => ({ imageId, source: "artwork" as const }));
  const trailers = pickTrailer(game.videos);
  return {
    id: `igdb-${game.id}`,
    igdbId: game.id,
    title: game.name,
    normalizedTitle: normalizeText(game.name),
    category: GAME_TYPE_LABELS[game.game_type ?? 0] ?? "Main",
    publishers,
    developers,
    platforms: getPlatformNames(game),
    genres: (game.genres ?? []).map(genre => genre.name ?? "").filter(Boolean),
    igdbUrl: game.url,
    sourceUrls: game.url ? [game.url] : [],
    updatedAt: game.updated_at,
    artworks,
    screenshots,
    trailers,
    ...date,
    ...eligibility
  };
}
