// Lower-case, punctuation-free text used for matching titles, companies and search terms.
export function normalizeText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
