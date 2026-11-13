import { normalizeText } from "../text/normalizeText";

export function scoreNameMatch(normalizedQueryTitle: string, candidateName: string) {
  const normalizedCandidate = normalizeText(candidateName);
  if (!normalizedCandidate || !normalizedQueryTitle) return 0;
  if (normalizedCandidate === normalizedQueryTitle) return 70;
  if (normalizedCandidate.includes(normalizedQueryTitle) || normalizedQueryTitle.includes(normalizedCandidate)) return 45;
  return 0;
}

export function scorePlatformMatch(queryPlatform: string, candidatePlatforms: string[]) {
  if (!queryPlatform) return 0;
  const normalizedQuery = normalizeText(queryPlatform);
  if (!normalizedQuery) return 0;
  const normalizedPlatforms = candidatePlatforms.map(normalizeText).filter(Boolean);
  if (normalizedPlatforms.some(platform => platform === normalizedQuery)) return 20;
  if (normalizedPlatforms.some(platform => platform.includes(normalizedQuery) || normalizedQuery.includes(platform))) return 12;
  return 0;
}
