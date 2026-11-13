import { completedGenres } from "../../../../shared/completedGenres";
import { wholeRating } from "../../../../shared/wholeRating";
import type { YearInReviewGame, YearInReviewPlayerType, YearInReviewShare, YearInReviewSummary, YearInReviewYear } from "../../../../shared/types";
import type { CompletedReviewRow } from "../completed/completedReadModel";
import { THRESHOLDS } from "./thresholds";

export interface YearInReviewInput {
  year: number;
  // The local date; decides the current year. Never read inside the calculation.
  today: Date;
  games: CompletedReviewRow[];
  // Lower-cased genres and exact platforms of every earlier year.
  earlier: { genres: string[]; platforms: string[] };
  // Finishes per completion year.
  years: Array<{ year: number; count: number }>;
  settings: { gotyCompletedId: string | null; musicVideoId: string | null };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const UNKNOWN_PLATFORM = "Unknown platform";
const DAY_MS = 86_400_000;

// The yearly recap of the Completed Library, from rows to summary. Pure: no database, no clock.
export function buildYearInReview(input: YearInReviewInput): YearInReviewSummary {
  const games = [...input.games].sort((left, right) => compareFinish(left, right));
  const toGame = (row: CompletedReviewRow): YearInReviewGame => ({
    id: row.id,
    title: row.title,
    coverImageId: row.coverImageId,
    ratingScore: row.ratingScore,
    userPlatform: row.userPlatform,
    finishLabel: finishLabel(row),
    month: monthOf(row)
  });
  const rated = games.filter(row => row.ratingScore !== null);
  const matched = games.filter(row => row.igdbId !== null);
  const dated = games.filter(row => monthOf(row) !== null);
  const previousYearCount = input.years.find(entry => entry.year === input.year - 1)?.count || null;
  const dayOne = games.filter(isDayOne);

  const months = Array.from({ length: 12 }, () => 0);
  for (const row of dated) months[monthOf(row)! - 1] += 1;
  const busiest = Math.max(0, ...months);

  const genres = topShares(games, row => completedGenres(row), games.length, Infinity);

  return {
    year: input.year,
    inProgress: input.year === input.today.getFullYear(),
    count: games.length,
    previousYearCount,
    coverage: { withMonth: dated.length, rated: rated.length, matched: matched.length },
    overview: {
      months,
      busiestMonth: busiest ? { month: months.indexOf(busiest) + 1, count: busiest } : null,
      averageRating: rated.length ? average(rated.map(row => row.ratingScore!)) : null,
      nineOrHigher: rated.filter(row => row.ratingScore! >= THRESHOLDS.nineOrHigher).length,
      first: dated.length ? toGame(dated[0]) : null,
      last: dated.length ? toGame(dated[dated.length - 1]) : null
    },
    taste: {
      genres: genres.slice(0, THRESHOLDS.topGenres),
      themes: topShares(matched, row => row.igdbThemes, matched.length, THRESHOLDS.topThemes),
      platforms: topShares(games, row => [row.userPlatform || UNKNOWN_PLATFORM], games.length, Infinity, exactName),
      developer: favourite(games, row => row.igdbDeveloper ?? row.developer),
      publisher: favourite(games, row => row.igdbPublisher ?? row.publisher),
      playModes: playModes(games),
      somethingNew: somethingNew(games, input)
    },
    ratings: {
      spread: rated.length ? spread(rated) : null,
      hotTake: hotTake(games, toGame),
      hiddenGem: hiddenGem(games, toGame),
      criticsAgreed: criticsAgreed(games),
      playerType: games.length ? playerType(games, rated, genres.length, dayOne.length) : null
    },
    timing: {
      dayOne: dayOne.length ? { games: dayOne.map(toGame) } : null,
      lateToTheParty: lateToTheParty(games, toGame),
      releaseRange: releaseRange(games, toGame),
      longestStreak: longestStreak(months)
    },
    goty: gameOfTheYear(games, rated, input.settings, toGame),
    games: games.map(toGame)
  };
}

// Years to offer in the picker: every year with a finish, newest first, plus the current year.
export function listReviewYears(years: Array<{ year: number; count: number }>, today: Date): YearInReviewYear[] {
  const current = today.getFullYear();
  const withGames = years.filter(entry => entry.count > 0);
  const all = withGames.some(entry => entry.year === current) ? withGames : [...withGames, { year: current, count: 0 }];
  return all
    .map(entry => ({ year: entry.year, count: entry.count, inProgress: entry.year === current }))
    .sort((left, right) => right.year - left.year);
}

// Finish order, used everywhere a card needs "first", "last" or a tie-break: exact dates, then month-only
// entries (as if on the last day of their month), then year-only entries, then title.
function finishSortKey(row: CompletedReviewRow) {
  if (row.completionPrecision === "exact" && row.completionDate) return row.completionDate;
  if (row.completionMonth) return `${row.completionMonth}-32`;
  return `${row.completionYear ?? 9999}-13`;
}

function compareFinish(left: CompletedReviewRow, right: CompletedReviewRow) {
  const byKey = finishSortKey(left).localeCompare(finishSortKey(right));
  return byKey || left.title.localeCompare(right.title);
}

function finishLabel(row: CompletedReviewRow) {
  if (row.completionPrecision === "exact" && row.completionDate) {
    const [year, month, day] = row.completionDate.split("-").map(Number);
    return `${day} ${MONTHS[month - 1]} ${year}`;
  }
  if (row.completionMonth) {
    const [year, month] = row.completionMonth.split("-").map(Number);
    return `${MONTHS[month - 1]} ${year}`;
  }
  return String(row.completionYear ?? "");
}

function monthOf(row: CompletedReviewRow) {
  const month = row.completionMonth ? Number(row.completionMonth.slice(5, 7)) : NaN;
  return month >= 1 && month <= 12 ? month : null;
}

const parseDay = (text: string) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text);
  return match ? { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) } : null;
};
const dayNumber = (date: { year: number; month: number; day: number }) => Date.UTC(date.year, date.month - 1, date.day) / DAY_MS;
const releaseOf = (row: CompletedReviewRow) => (row.igdbReleaseDate ? parseDay(row.igdbReleaseDate) : null);

// The date a finish can be measured from: its exact date, or the first of its month. Year-only has none.
function finishAnchor(row: CompletedReviewRow) {
  if (row.completionPrecision === "exact" && row.completionDate) return parseDay(row.completionDate);
  if (row.completionMonth) return parseDay(`${row.completionMonth}-01`);
  return null;
}

function isDayOne(row: CompletedReviewRow) {
  const release = releaseOf(row);
  if (!release) return false;
  if (row.completionPrecision === "exact" && row.completionDate) {
    const finish = parseDay(row.completionDate);
    const days = finish ? dayNumber(finish) - dayNumber(release) : -1;
    return days >= 0 && days <= THRESHOLDS.dayOneMaxDays;
  }
  if (!row.completionMonth) return false;
  const finish = parseDay(`${row.completionMonth}-01`)!;
  const monthsAfter = finish.year * 12 + finish.month - (release.year * 12 + release.month);
  return monthsAfter === 0 || monthsAfter === 1;
}

function wholeYearsBetween(from: { year: number; month: number; day: number }, to: { year: number; month: number; day: number }) {
  const beforeAnniversary = to.month < from.month || (to.month === from.month && to.day < from.day);
  return to.year - from.year - (beforeAnniversary ? 1 : 0);
}

const average = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;

function median(values: number[]) {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

// Counts each name once per game, case-insensitively by default, keeping the first spelling seen.
// Platforms pass `exactName`: they are counted as entered, like the Completed Library platform filter.
const foldCase = (name: string) => name.toLowerCase();
const exactName = (name: string) => name;

function countNames(games: CompletedReviewRow[], namesOf: (row: CompletedReviewRow) => Array<string | null | undefined>, keyOf = foldCase) {
  const counts = new Map<string, { name: string; count: number; ids: string[] }>();
  for (const row of games) {
    const seen = new Set<string>();
    for (const raw of namesOf(row)) {
      const name = raw?.trim();
      if (!name) continue;
      const key = keyOf(name);
      if (seen.has(key)) continue;
      seen.add(key);
      const entry = counts.get(key) ?? { name, count: 0, ids: [] };
      entry.count += 1;
      entry.ids.push(row.id);
      counts.set(key, entry);
    }
  }
  return [...counts.values()].sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
}

function topShares(games: CompletedReviewRow[], namesOf: (row: CompletedReviewRow) => string[], total: number, limit: number, keyOf = foldCase): YearInReviewShare[] {
  if (!total) return [];
  return countNames(games, namesOf, keyOf).slice(0, limit).map(entry => ({ ...entry, share: entry.count / total }));
}

function favourite(games: CompletedReviewRow[], nameOf: (row: CompletedReviewRow) => string | null) {
  const [top] = countNames(games, row => [nameOf(row)]);
  return top && top.count >= THRESHOLDS.favouriteMinGames ? { name: top.name, count: top.count } : null;
}

function playModes(games: CompletedReviewRow[]) {
  const withModes = games.filter(row => row.igdbGameModes.length);
  if (!withModes.length) return null;
  const together = withModes.filter(row => row.igdbGameModes.some(mode => /multi|co-?op|mmo|split screen|battle royale/i.test(mode))).length;
  return { solo: withModes.length - together, together };
}

function somethingNew(games: CompletedReviewRow[], input: YearInReviewInput) {
  if (!input.years.some(entry => entry.year < input.year && entry.count > 0)) return null;
  const knownGenres = new Set(input.earlier.genres.map(genre => genre.toLowerCase()));
  const knownPlatforms = new Set(input.earlier.platforms);
  const genres = countNames(games, row => completedGenres(row)).map(entry => entry.name).filter(name => !knownGenres.has(name.toLowerCase()));
  const platforms = [...new Set(games.map(row => row.userPlatform).filter(platform => platform && !knownPlatforms.has(platform)))];
  return genres.length || platforms.length ? { genres, platforms } : null;
}

function spread(rated: CompletedReviewRow[]) {
  const buckets = Array.from({ length: 11 }, () => 0);
  for (const row of rated) buckets[wholeRating(row.ratingScore!)] += 1;
  return buckets;
}

const withCriticScore = (games: CompletedReviewRow[]) =>
  games.filter(row => row.ratingScore !== null && row.igdbAggregatedRating !== null);
const criticGap = (row: CompletedReviewRow) => Math.abs(row.ratingScore! * 10 - row.igdbAggregatedRating!);

function hotTake(games: CompletedReviewRow[], toGame: (row: CompletedReviewRow) => YearInReviewGame) {
  let best: CompletedReviewRow | null = null;
  for (const row of withCriticScore(games)) {
    if (criticGap(row) >= THRESHOLDS.hotTakeMinGap && (!best || criticGap(row) > criticGap(best))) best = row;
  }
  return best ? { game: toGame(best), rating: best.ratingScore!, criticScore: Math.round(best.igdbAggregatedRating!) } : null;
}

function hiddenGem(games: CompletedReviewRow[], toGame: (row: CompletedReviewRow) => YearInReviewGame) {
  let best: CompletedReviewRow | null = null;
  for (const row of games) {
    if (row.igdbId === null || row.ratingScore === null || row.ratingScore < THRESHOLDS.hiddenGemMinRating) continue;
    if ((row.igdbTotalRatingCount ?? 0) >= THRESHOLDS.hiddenGemMaxRatingCount) continue;
    if (!best || row.ratingScore > best.ratingScore!) best = row;
  }
  return best ? { game: toGame(best), ratingCount: best.igdbTotalRatingCount ?? 0 } : null;
}

function criticsAgreed(games: CompletedReviewRow[]) {
  const compared = withCriticScore(games);
  if (!compared.length) return null;
  return { agreed: compared.filter(row => criticGap(row) <= THRESHOLDS.criticsAgreeWithin).length, total: compared.length };
}

function playerType(games: CompletedReviewRow[], rated: CompletedReviewRow[], genreCount: number, dayOneCount: number): { key: YearInReviewPlayerType; reason: string } {
  const rules = THRESHOLDS.playerType;
  const averageRating = rated.length ? average(rated.map(row => row.ratingScore!)) : null;
  if (averageRating !== null && rated.length >= rules.critic.minRated && averageRating < rules.critic.maxAverage) {
    return { key: "critic", reason: `Your average was ${averageRating.toFixed(1)} across ${rated.length} rated games` };
  }
  const [topPlatform] = countNames(games, row => [row.userPlatform], exactName);
  if (games.length >= rules.loyalist.minGames && topPlatform && topPlatform.count / games.length >= rules.loyalist.minShare) {
    return { key: "loyalist", reason: `${Math.round((topPlatform.count / games.length) * 100)}% of your games were on ${topPlatform.name}` };
  }
  if (genreCount >= rules.explorer.minGenres) return { key: "explorer", reason: `You played ${genreCount} different genres` };
  const ages = games.flatMap(row => {
    const release = releaseOf(row);
    return release && row.completionYear !== null ? [Math.max(0, row.completionYear - release.year)] : [];
  });
  if (ages.length >= rules.timeTraveller.minDated && median(ages) >= rules.timeTraveller.minMedianYears) {
    return { key: "time-traveller", reason: `Your median game was ${Math.round(median(ages))} years old` };
  }
  if (dayOneCount >= rules.dayOneHero.minGames) return { key: "day-one-hero", reason: `${dayOneCount} games finished within a month of release` };
  if (games.length >= rules.completionist.minGames) return { key: "completionist", reason: `${games.length} games finished` };
  return { key: "adventurer", reason: "A bit of everything" };
}

function lateToTheParty(games: CompletedReviewRow[], toGame: (row: CompletedReviewRow) => YearInReviewGame) {
  let best: { row: CompletedReviewRow; years: number; releaseYear: number } | null = null;
  for (const row of games) {
    const release = releaseOf(row);
    const finish = finishAnchor(row);
    if (!release || !finish) continue;
    const years = wholeYearsBetween(release, finish);
    if (years >= THRESHOLDS.lateMinYears && (!best || years > best.years)) best = { row, years, releaseYear: release.year };
  }
  return best ? { game: toGame(best.row), years: best.years, releaseYear: best.releaseYear } : null;
}

function releaseRange(games: CompletedReviewRow[], toGame: (row: CompletedReviewRow) => YearInReviewGame) {
  const released = games.flatMap(row => {
    const release = releaseOf(row);
    return release ? [{ row, release }] : [];
  });
  if (!released.length) return null;
  const byDate = [...released].sort((left, right) => dayNumber(left.release) - dayNumber(right.release));
  const oldest = byDate[0];
  const newest = byDate[byDate.length - 1];
  return {
    oldest: { game: toGame(oldest.row), year: oldest.release.year },
    newest: { game: toGame(newest.row), year: newest.release.year }
  };
}

function longestStreak(months: number[]) {
  let best = { months: 0, from: 0, to: 0 };
  let start = -1;
  months.forEach((count, index) => {
    if (!count) {
      start = -1;
      return;
    }
    if (start < 0) start = index;
    if (index - start + 1 > best.months) best = { months: index - start + 1, from: start + 1, to: index + 1 };
  });
  return best.months >= THRESHOLDS.streakMinMonths ? best : null;
}

function gameOfTheYear(
  games: CompletedReviewRow[],
  rated: CompletedReviewRow[],
  settings: YearInReviewInput["settings"],
  toGame: (row: CompletedReviewRow) => YearInReviewGame
): YearInReviewSummary["goty"] {
  if (!games.length) return null;
  const override = settings.gotyCompletedId ? games.find(row => row.id === settings.gotyCompletedId) : undefined;
  // Games are in finish order, so the last of the best-rated is the later finish.
  const bestRating = rated.length ? Math.max(...rated.map(row => row.ratingScore!)) : null;
  const automatic = bestRating === null ? games[games.length - 1] : rated.filter(row => row.ratingScore === bestRating).pop()!;
  const pick = override ?? automatic;
  const screenshot = pick.screenshots.find(shot => shot.imageId)?.imageId;
  return {
    game: toGame(pick),
    isOverride: Boolean(override),
    isLatestFinish: !override && bestRating === null,
    note: pick.notes?.trim() || null,
    backdrop: screenshot ? { imageId: screenshot, kind: "screenshot" } : pick.coverImageId ? { imageId: pick.coverImageId, kind: "cover" } : null,
    musicVideoId: settings.musicVideoId
  };
}
