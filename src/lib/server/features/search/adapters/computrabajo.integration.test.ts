import { afterAll, beforeEach, describe, expect, test } from 'bun:test';
import { rmSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { eq, inArray } from 'drizzle-orm';
import { BlockedError } from '$lib/server/shared/http';
import type { HttpClient } from '$lib/server/shared/http';
import { computrabajo } from './computrabajo';
import type { PageLogEntry, SearchContext } from './types';
import { db } from '$lib/server/db/client';
import { companies, postings, publications, searchPageLogs } from '$lib/server/db/schema';
import { countPageOutcomes, listPageLogs, recordPageLog, resumePageFor } from '../page-log';
import { savePosting } from '$lib/server/features/postings/commands/save-posting';

// Corre contra una base SQLite temporal: scripts/test-preload.ts fija JOBFILTER_DB ahí,
// así que nunca se toca la base real de data/jobfilter.db.
const TMP_DB = resolve('data/test-jobfilter.db');
const PLATFORM = computrabajo.id;
const TERM = 'desarrollador fullstack';
const LOCATION = { country: 'Colombia', city: 'Bogotá', languages: ['es'] };

const fixture = (name: string) => readFileSync(resolve('fixtures/computrabajo', name), 'utf8');
const pageOf = (url: string) => Number(new URL(url).searchParams.get('p') ?? '1');
const placeOf = (url: string) => url.match(/-en-(.+)\?/)?.[1] ?? '';

function pageHtml(total: number, suffix: string): string {
	const safe = suffix.replace(/[^\w]/g, '');
	return fixture('busqueda-fullstack.html')
		.replace(/(<h1 class="title_page"[\s\S]*?<span class="fwB">\s*)[\d.]+(\s*<\/span>)/, `$1${total}$2`)
		.replace(/data-id='(\w+)'/g, `data-id='$1${safe}'`)
		.replace(/(en-bogota-dc-)(\w+)/g, `$1$2${safe}`);
}

type Route = (url: string) => string;

function fakeClient(routes: Record<string, Route>): HttpClient & { urls: string[] } {
	const urls: string[] = [];
	return {
		urls,
		async text(url) {
			urls.push(url);
			const route = routes[`${placeOf(url)}:${pageOf(url)}`];
			if (!route) throw new Error(`sin fixture para ${placeOf(url)}:${pageOf(url)}`);
			return route(url);
		},
		json: async () => {
			throw new Error('no usado');
		},
		requests: () => urls.length,
		rateLimited: () => false
	};
}

/**
 * Ejecuta el adapter igual que start-search: cada página se guarda en la base y el reintento
 * se decide con la bitácora persistida. Guarda las vacantes entregadas como hace el comando.
 */
async function runWithDb(client: HttpClient & { urls: string[] }) {
	const ctx: SearchContext = {
		client,
		since: new Date('2000-01-01'),
		location: LOCATION,
		recordPage: (entry: PageLogEntry) => recordPageLog({ platform: PLATFORM, term: TERM, ...entry }),
		resumePage: (_term, place) => resumePageFor(PLATFORM, TERM, place)
	};
	const saved: string[] = [];
	let error: unknown;
	try {
		for await (const posting of computrabajo.search(TERM, ctx)) {
			if (savePosting(PLATFORM, posting)) saved.push(posting.externalId);
		}
	} catch (err) {
		error = err;
	}
	return { saved, error };
}

beforeEach(() => {
	// cada prueba parte de una bitácora y unas vacantes limpias para esta plataforma
	db.delete(searchPageLogs).run();
	// las publicaciones y las vacantes referencian compañías: se borran en orden de claves foráneas
	const ids = db
		.select({ id: postings.id })
		.from(postings)
		.where(eq(postings.platform, PLATFORM))
		.all()
		.map((r) => r.id);
	if (ids.length) db.delete(publications).where(inArray(publications.postingId, ids)).run();
	db.delete(postings).where(eq(postings.platform, PLATFORM)).run();
	db.delete(companies).run();
});

afterAll(() => {
	try {
		rmSync(TMP_DB, { force: true });
		rmSync(`${TMP_DB}-wal`, { force: true });
		rmSync(`${TMP_DB}-shm`, { force: true });
	} catch {
		// en Windows el archivo puede quedar tomado por el driver; no es parte de la prueba
	}
});

describe('bitácora persistida y reanudación (integración con SQLite)', () => {
	test('corrida normal: registra cada página con su resultado y la bitácora queda consultable', async () => {
		const client = fakeClient({
			'remoto:1': () => pageHtml(50, 'a1'),
			'remoto:2': () => pageHtml(50, 'a2'),
			'remoto:3': () => pageHtml(50, 'a3'),
			'bogota:1': () => pageHtml(5, 'city')
		});
		const { error, saved } = await runWithDb(client);
		expect(error).toBeUndefined();
		expect(saved.length).toBeGreaterThan(0);

		const logs = listPageLogs(PLATFORM);
		expect(logs).toHaveLength(4); // 3 remotas + 1 de ciudad
		const remote = logs.filter((l) => l.place === 'remoto').sort((a, b) => a.page - b.page);
		expect(remote.map((l) => [l.page, l.outcome, l.parsed])).toEqual([
			[1, 'ok', 10],
			[2, 'ok', 10],
			[3, 'sin-paginas', 10]
		]);
		expect(logs.every((l) => l.term === TERM)).toBe(true);
		// 2 remotas 'ok', la remota 3 y la de ciudad cortan por sin-paginas
		expect(countPageOutcomes(PLATFORM)).toMatchObject({ ok: 2, 'sin-paginas': 2, 'sin-novedades': 0, bloqueado: 0, error: 0 });
	});

	test('BlockedError en la página 2: se guarda el bloqueo, las vacantes persisten y se reanuda en la 2', async () => {
		const client1 = fakeClient({
			'remoto:1': () => pageHtml(50, 'b1'),
			'remoto:2': () => {
				throw new BlockedError('HTTP 429');
			}
		});
		const first = await runWithDb(client1);
		expect(first.error).toBeInstanceOf(BlockedError);
		expect(first.saved).toHaveLength(8); // 10 parseadas, 8 tras el filtro de ubicación

		// lo guardado antes del fallo sigue en la base
		const stored = db.select().from(postings).where(eq(postings.platform, PLATFORM)).all();
		expect(stored).toHaveLength(8);

		// la bitácora marca la página 2 como bloqueada y el cursor pide reanudar ahí
		expect(resumePageFor(PLATFORM, TERM, 'remoto')).toBe(2);
		const blocked = listPageLogs(PLATFORM).find((l) => l.page === 2)!;
		expect(blocked.outcome).toBe('bloqueado');
		expect(blocked.error).toContain('429');

		// segunda corrida: la página 1 NO se vuelve a pedir; arranca en la 2 y termina bien
		const client2 = fakeClient({
			'remoto:2': () => pageHtml(50, 'b2'),
			'remoto:3': () => pageHtml(50, 'b3'),
			'bogota:1': () => pageHtml(5, 'city2')
		});
		const second = await runWithDb(client2);
		expect(second.error).toBeUndefined();
		const remotePages = client2.urls.filter((u) => placeOf(u) === 'remoto').map(pageOf);
		expect(remotePages).toEqual([2, 3]);
		// no se duplicaron las vacantes de la página 1 (mismos externalId)
		const after = db.select().from(postings).where(eq(postings.platform, PLATFORM)).all();
		expect(new Set(after.map((p) => p.externalId)).size).toBe(after.length);
		expect(after.length).toBeGreaterThan(8);

		// tras terminar bien, una nueva búsqueda vuelve a arrancar por la página 1
		expect(resumePageFor(PLATFORM, TERM, 'remoto')).toBe(1);
	});

	test('un error común en la página 2 también reanuda en la página fallida', async () => {
		const client1 = fakeClient({
			'remoto:1': () => pageHtml(50, 'c1'),
			'remoto:2': () => {
				throw new Error('ECONNRESET');
			}
		});
		const first = await runWithDb(client1);
		expect(first.error).not.toBeInstanceOf(BlockedError);
		expect(listPageLogs(PLATFORM).find((l) => l.page === 2)?.outcome).toBe('error');
		expect(resumePageFor(PLATFORM, TERM, 'remoto')).toBe(2);

		const client2 = fakeClient({
			'remoto:2': () => pageHtml(50, 'c2'),
			'remoto:3': () => pageHtml(50, 'c3'),
			'bogota:1': () => pageHtml(5, 'city3')
		});
		const second = await runWithDb(client2);
		expect(second.error).toBeUndefined();
		expect(client2.urls.filter((u) => placeOf(u) === 'remoto').map(pageOf)).toEqual([2, 3]);
	});

	test('una palabra que terminó por sin-novedades vuelve a empezar por la página 1 la próxima vez', async () => {
		// primera corrida: la página 1 no trae nada reciente (corte normal, no un fallo)
		const client1 = fakeClient({
			'remoto:1': () => pageHtml(50, 'd1'),
			'bogota:1': () => pageHtml(5, 'dcity')
		});
		const ctxStale: SearchContext = {
			client: client1,
			since: new Date('2030-01-01'),
			location: LOCATION,
			recordPage: (entry) => recordPageLog({ platform: PLATFORM, term: TERM, ...entry }),
			resumePage: (_t, place) => resumePageFor(PLATFORM, TERM, place)
		};
		for await (const _ of computrabajo.search(TERM, ctxStale)) {
			// sin vacantes recientes
		}
		const outcomes = listPageLogs(PLATFORM).map((l) => l.outcome);
		expect(outcomes.every((o) => o === 'sin-novedades')).toBe(true);
		// no hay fallo registrado: el cursor normal manda a la página 1
		expect(resumePageFor(PLATFORM, TERM, 'remoto')).toBe(1);
		expect(resumePageFor(PLATFORM, TERM, 'bogota')).toBe(1);

		// la próxima búsqueda arranca efectivamente pidiendo la página 1; con total chico se
		// detiene en esa página y no necesita más rutas
		const client2 = fakeClient({
			'remoto:1': () => pageHtml(10, 'e1'),
			'bogota:1': () => pageHtml(5, 'ecity')
		});
		const second = await runWithDb(client2);
		expect(second.error).toBeUndefined();
		expect(client2.urls.filter((u) => placeOf(u) === 'remoto').map(pageOf)).toEqual([1]);
	});

	test('cada fila guarda palabra, lugar, página, resultado, vacantes y marca de tiempo', async () => {
		const client = fakeClient({
			'remoto:1': () => pageHtml(10, 'f1'),
			'bogota:1': () => pageHtml(5, 'fcity')
		});
		await runWithDb(client);
		const row = listPageLogs(PLATFORM).find((l) => l.place === 'remoto')!;
		expect(row).toMatchObject({
			platform: PLATFORM,
			term: TERM,
			place: 'remoto',
			placeLabel: 'remoto (todo el país)',
			page: 1,
			outcome: 'sin-paginas',
			parsed: 10,
			error: null
		});
		expect(Number.isNaN(Date.parse(row.attemptedAt))).toBe(false);
	});
});
