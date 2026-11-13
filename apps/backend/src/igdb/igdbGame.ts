import type { GameTrailer, IgdbGameLike } from "../../../../shared/types";
import { normalizeText } from "../text/normalizeText";

// Reading fields out of raw IGDB game payloads. No Upcoming rules live here.

export function unixToIso(seconds: number) {
  return new Date(seconds * 1000).toISOString().slice(0, 10);
}

export function unixToText(seconds: number) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(seconds * 1000));
}

export function getCompanyNames(game: IgdbGameLike, role?: "developer" | "publisher") {
  return (game.involved_companies ?? [])
    .filter(company => !role || Boolean(company[role]))
    .map(company => company.company?.name)
    .filter((name): name is string => Boolean(name));
}

export function getPlatformNames(game: IgdbGameLike) {
  return (game.platforms ?? [])
    .map(platform => platform.abbreviation || platform.name || platform.slug)
    .filter((name): name is string => Boolean(name));
}

export function pickTrailer(videos: IgdbGameLike["videos"]): GameTrailer[] {
  type TrailerCandidate = GameTrailer & { name: string | null; rank: number; index: number };
  const candidates = (videos ?? [])
    .map((video, index) => {
      const videoId = sanitizeYoutubeVideoId(video.video_id);
      if (!videoId) return null;
      return {
        videoId,
        name: video.name?.trim() || null,
        provider: "youtube" as const,
        rank: trailerRank(video.name),
        index
      } satisfies TrailerCandidate;
    })
    .filter((video): video is TrailerCandidate => Boolean(video))
    .sort((a, b) => a.rank - b.rank || a.index - b.index);

  const selected = candidates[0];
  return selected ? [{ videoId: selected.videoId, name: selected.name, provider: selected.provider }] : [];
}

function sanitizeYoutubeVideoId(value: string | undefined) {
  const id = value?.trim();
  if (!id) return null;
  return /^[A-Za-z0-9_-]{6,}$/.test(id) ? id : null;
}

function trailerRank(name: string | undefined) {
  const normalized = normalizeText(name ?? "");
  if (normalized.includes("gameplay")) return 0;
  if (normalized.includes("announcement") || normalized.includes("announce")) return 1;
  if (normalized.includes("trailer") || normalized.includes("overview")) return 2;
  return 3;
}
