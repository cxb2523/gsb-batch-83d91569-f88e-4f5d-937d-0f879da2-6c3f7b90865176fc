// Freno para plataformas que bloquean por volumen (LinkedIn): apretar Buscar muchas veces no
// debe traducirse en muchas peticiones. Sin base de datos, para poder probarlo solo.

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** Si la última corrida empezó hace menos de `minGapMinutes`, hasta cuándo esperar (ISO). */
export function gapUntil(lastStart: string | null, minGapMinutes: number | undefined, now = Date.now()): string | null {
	if (!lastStart || !minGapMinutes) return null;
	const until = Date.parse(lastStart) + minGapMinutes * MINUTE;
	return until > now ? new Date(until).toISOString() : null;
}

/**
 * Las palabras que todavía tocan: las que nunca se buscaron o cuya última búsqueda completa
 * tiene más de `refreshEveryHours`. Si no queda ninguna, `nextAt` dice cuándo vuelve a tocar
 * la primera.
 */
export function dueKeywords<T extends { term: string }>(
	keywords: T[],
	cursors: Map<string, string>,
	refreshEveryHours: number | undefined,
	now = Date.now()
): { due: T[]; nextAt: string | null } {
	if (!refreshEveryHours || !keywords.length) return { due: keywords, nextAt: null };
	const dueAt = (k: T) => {
		const cursor = cursors.get(k.term);
		return cursor ? Date.parse(cursor) + refreshEveryHours * HOUR : 0;
	};
	const due = keywords.filter((k) => dueAt(k) <= now);
	const next = due.length ? null : Math.min(...keywords.map(dueAt));
	return { due, nextAt: next ? new Date(next).toISOString() : null };
}
