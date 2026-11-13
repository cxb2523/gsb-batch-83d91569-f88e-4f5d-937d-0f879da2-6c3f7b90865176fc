import { normalizeText } from "../text/normalizeText";

export function completedIdentityKey(title: string, userPlatform = "") {
  return `${normalizeText(title)}|${normalizeText(userPlatform)}`;
}

export function completedGameId(title: string, userPlatform = "") {
  const titleSlug = normalizeText(title).replace(/\s+/g, "-") || "game";
  const platformSlug = normalizeText(userPlatform).replace(/\s+/g, "-");
  return `completed-${[titleSlug, platformSlug].filter(Boolean).join("-")}`;
}
