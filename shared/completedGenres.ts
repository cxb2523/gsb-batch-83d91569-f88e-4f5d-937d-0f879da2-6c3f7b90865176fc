// A completed game's genres are its saved genres (from the retired Excel import) plus its IGDB genres. The Completed Library Genre
// filter and the Year in Review taste cards both use this one rule, so they never disagree.
export function completedGenres(item: { genres: string[]; igdbGenres?: string[] | null }) {
  return [...item.genres, ...(item.igdbGenres ?? [])];
}
