// Bitácora de páginas: cada petición de una palabra en un lugar deja una fila, con el
// resultado (éxito, corte normal o fallo) y cuántas vacantes trajo. Uso interno del slice
// de búsqueda; la página y los logs la leen con las consultas de este archivo.
import { desc, eq, and, sql } from 'drizzle-orm';
import { db } from '$lib/server/db/client';
import { searchPageLogs } from '$lib/server/db/schema';
import { PAGE_OUTCOMES, type PageOutcome } from './adapters/types';

export { PAGE_OUTCOMES };
export type { PageOutcome };

/** Una fila de la bitácora, tal como queda en la base. */
export type PageLog = {
	id: number;
	platform: string;
	term: string;
	place: string;
	placeLabel: string;
	page: number;
	outcome: PageOutcome;
	parsed: number;
	error: string | null;
	attemptedAt: string;
};

export type RecordPageInput = {
	platform: string;
	term: string;
	place: string;
	placeLabel: string;
	page: number;
	outcome: PageOutcome;
	parsed: number;
	error?: string | null;
	attemptedAt?: string;
};

/** Guarda el resultado de una página pedida durante la búsqueda. */
export function recordPageLog(input: RecordPageInput): void {
	db.insert(searchPageLogs)
		.values({
			platform: input.platform,
			term: input.term,
			place: input.place,
			placeLabel: input.placeLabel,
			page: input.page,
			outcome: input.outcome,
			parsed: input.parsed,
			error: input.error,
			attemptedAt: input.attemptedAt ?? new Date().toISOString()
		})
		.run();
}

function rowToLog(row: typeof searchPageLogs.$inferSelect): PageLog {
	return {
		id: row.id,
		platform: row.platform,
		term: row.term,
		place: row.place,
		placeLabel: row.placeLabel,
		page: row.page,
		outcome: row.outcome as PageOutcome,
		parsed: row.parsed,
		error: row.error,
		attemptedAt: row.attemptedAt
	};
}

/**
 * Página por la que hay que reintentar una palabra en un lugar: si lo último que se registró
 * fue un fallo (bloqueo u otro error), esa misma página; si el último intento terminó bien o
 * nunca se buscó, la 1, que es donde arranca el cursor normal.
 */
export function resumePageFor(platform: string, term: string, place: string): number {
	const row = db
		.select()
		.from(searchPageLogs)
		.where(
			and(eq(searchPageLogs.platform, platform), eq(searchPageLogs.term, term), eq(searchPageLogs.place, place))
		)
		.orderBy(desc(searchPageLogs.attemptedAt), desc(searchPageLogs.id))
		.limit(1)
		.get();
	return row && (row.outcome === 'bloqueado' || row.outcome === 'error') ? row.page : 1;
}

/** Fila más reciente de una plataforma que terminó en fallo, para el detalle de la barra de progreso. */
export function latestFailedPage(platform: string): PageLog | null {
	const row = db
		.select()
		.from(searchPageLogs)
		.where(eq(searchPageLogs.platform, platform))
		.orderBy(desc(searchPageLogs.attemptedAt), desc(searchPageLogs.id))
		.limit(1)
		.get();
	if (!row || (row.outcome !== 'bloqueado' && row.outcome !== 'error')) return null;
	return rowToLog(row);
}

/** Últimas filas de la bitácora de una plataforma; sin límite, toda la historia de la corrida. */
export function listPageLogs(platform: string, limit = 200): PageLog[] {
	return db
		.select()
		.from(searchPageLogs)
		.where(eq(searchPageLogs.platform, platform))
		.orderBy(desc(searchPageLogs.attemptedAt), desc(searchPageLogs.id))
		.limit(limit)
		.all()
		.map(rowToLog);
}

/**
 * Cuántas filas hay de cada resultado en una plataforma. Sirve para los tests y para un
 * resumen rápido sin traer todas las filas.
 */
export function countPageOutcomes(platform: string): Record<PageOutcome, number> {
	const rows = db
		.select({ outcome: searchPageLogs.outcome, n: sql<number>`count(*)` })
		.from(searchPageLogs)
		.where(eq(searchPageLogs.platform, platform))
		.groupBy(searchPageLogs.outcome)
		.all();
	const counts = Object.fromEntries(PAGE_OUTCOMES.map((o) => [o, 0])) as Record<PageOutcome, number>;
	for (const row of rows) counts[row.outcome as PageOutcome] = Number(row.n);
	return counts;
}
