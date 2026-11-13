export function genreOptions<T>(items: T[], genresOf: (item: T) => string[]) {
  const byKey = new Map<string, string>();
  for (const item of items) {
    for (const genre of genresOf(item)) {
      const name = genre.trim();
      if (name && !byKey.has(name.toLowerCase())) byKey.set(name.toLowerCase(), name);
    }
  }
  return [...byKey.values()].sort((left, right) => left.localeCompare(right));
}

export function filterByGenre<T>(items: T[], genre: string, genresOf: (item: T) => string[]) {
  const wanted = genre.trim().toLowerCase();
  if (!wanted) return items;
  return items.filter(item => genresOf(item).some(name => name.trim().toLowerCase() === wanted));
}
