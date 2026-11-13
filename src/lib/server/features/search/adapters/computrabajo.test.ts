import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { BlockedError, BudgetExhaustedError } from '$lib/server/shared/http';
import type { HttpClient } from '$lib/server/shared/http';
import type { PageLogEntry } from './types';
import { computrabajo, parseDetail, parseSearchPage, siteFor, slug } from './computrabajo';

const fixture = (name: string) => readFileSync(resolve('fixtures/computrabajo', name), 'utf8');
const ORIGIN = 'https://co.computrabajo.com';
const NOW = new Date('2026-10-14T20:00:00Z');

describe('parseSearchPage', () => {
	const { postings, total } = parseSearchPage(fixture('busqueda-fullstack.html'), ORIGIN, NOW);

	test('lee todas las tarjetas y el total', () => {
		expect(total).toBe(10);
		expect(postings).toHaveLength(10);
	});

	test('arma la vacante desde la tarjeta', () => {
		expect(postings[0]).toMatchObject({
			externalId: 'A6562AE092EDF60661373E686DCF3405',
			url: `${ORIGIN}/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-fullstack-java-en-bogota-dc-A6562AE092EDF60661373E686DCF3405`,
			title: 'Desarrollador fullstack Java',
			company: 'Db System SAS',
			location: 'Bogotá, D.C., Bogotá, D.C.',
			modality: 'presencial',
			publishedRaw: 'Hace 1 hora'
		});
		expect(postings[0].publishedAt.toISOString().slice(0, 10)).toBe('2026-10-14');
	});

	test('una empresa confidencial no se guarda como empresa', () => {
		const confidential = postings.find((p) => p.company === null);
		expect(confidential?.recruiter).toBe('Importante empresa del sector');
	});

	test('convierte las fechas relativas', () => {
		const ayer = postings.find((p) => p.publishedRaw === 'Ayer');
		expect(ayer?.publishedAt.toISOString().slice(0, 10)).toBe('2026-10-13');
		expect(ayer?.publishedApprox).toBeUndefined();
	});

	test('"Más de 30 días" y fechas absolutas', () => {
		const all = ['busqueda-remoto.html', 'busqueda-ciudad.html'].flatMap(
			(f) => parseSearchPage(fixture(f), ORIGIN, NOW).postings
		);
		const old = all.find((p) => p.publishedRaw === 'Más de 30 días');
		expect(old?.publishedApprox).toBe(true);
		const absolute = all.find((p) => /^\d+ de /.test(p.publishedRaw));
		expect(absolute?.publishedApprox).toBeUndefined();
		expect(absolute!.publishedAt < NOW).toBe(true);
	});
});

describe('modalidad', () => {
	test('reconoce remoto e híbrido', () => {
		const { postings } = parseSearchPage(fixture('busqueda-remoto.html'), ORIGIN, NOW);
		expect(postings.length).toBeGreaterThan(0);
		expect(postings.some((p) => p.modality === 'remoto')).toBe(true);
	});

	test('decodifica las entidades del link y quita el ancla', () => {
		const { postings } = parseSearchPage(fixture('busqueda-ciudad.html'), ORIGIN, NOW);
		const p = postings.find((x) => x.externalId === 'DE3D30CD71A3375761373E686DCF3405');
		expect(p?.url).toBe(
			`${ORIGIN}/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador%C2%A0backend-chatbot-y-automatizacion-conversacional-en-barranquilla-DE3D30CD71A3375761373E686DCF3405`
		);
	});

	test('la búsqueda por ciudad trae vacantes de esa ciudad', () => {
		const { postings } = parseSearchPage(fixture('busqueda-ciudad.html'), ORIGIN, NOW);
		expect(postings.some((p) => p.location?.startsWith('Barranquilla'))).toBe(true);
	});
});

describe('parseDetail', () => {
	test('extrae la descripción con requisitos y conocimientos', () => {
		const { description } = parseDetail(fixture('detalle.html'));
		expect(description).toContain('Spring Boot');
		expect(description).toContain('Conocimientos: Resolución de problemas, Java, Javascript');
		expect(description).not.toContain('Aptitudes asociadas');
		expect(description).not.toContain('<');
	});

	test('sin bloque de descripción devuelve vacío', () => {
		expect(parseDetail('<html></html>')).toEqual({});
	});
});

describe('URLs', () => {
	test('slug como lo arma el sitio', () => {
		expect(slug('Desarrollador .NET')).toBe('desarrollador-net');
		expect(slug('node.js')).toBe('node-js');
		expect(slug('Bogotá')).toBe('bogota');
	});

	test('un subdominio por país', () => {
		expect(siteFor('Colombia')).toBe(ORIGIN);
		expect(siteFor('México')).toBe('https://mx.computrabajo.com');
		expect(siteFor('Narnia')).toBeNull();
	});
});

// --- Búsqueda con bitácora página por página y reanudación -------------------------------

const LOCATION = { country: 'Colombia', city: 'Bogotá', languages: ['es'] };
const TERM = 'desarrollador fullstack';

const pageOf = (url: string) => Number(new URL(url).searchParams.get('p') ?? '1');
const placeOf = (url: string) => url.match(/-en-(.+)\?/)?.[1] ?? '';

/** HTML del fixture con otro total y tarjetas cambiadas de id, para simular varias páginas. */
function pageHtml(total: number, suffix: string): string {
	// el sufijo solo puede traer caracteres de palabra: data-id y la URL usan \w, y un guion
	// rompería el parseo de la tarjeta
	const safe = suffix.replace(/[^\w]/g, '');
	return fixture('busqueda-fullstack.html')
		.replace(/(<h1 class="title_page"[\s\S]*?<span class="fwB">\s*)[\d.]+(\s*<\/span>)/, `$1${total}$2`)
		.replace(/data-id='(\w+)'/g, `data-id='$1${safe}'`)
		.replace(/(en-bogota-dc-)(\w+)/g, `$1$2${safe}`);
}

/** Cliente falso: respuestas por (lugar, página) y errores de página controlables. */
function fakeClient(handlers: Record<string, (url: string) => string>): HttpClient & { urls: string[] } {
	const urls: string[] = [];
	return {
		urls,
		async text(url) {
			urls.push(url);
			const key = `${placeOf(url)}:${pageOf(url)}`;
			const handler = handlers[key];
			if (!handler) throw new Error(`sin fixture para ${key}`);
			return handler(url);
		},
		json: async () => {
			throw new Error('no usado');
		},
		requests: () => urls.length,
		rateLimited: () => false
	};
}

type RunResult = { logs: PageLogEntry[]; ids: string[]; error?: unknown; urls: string[] };

async function runSearch(
	client: HttpClient & { urls: string[] },
	resumePage?: (term: string, place: string) => number
): Promise<RunResult> {
	const logs: PageLogEntry[] = [];
	const ids: string[] = [];
	let error: unknown;
	try {
		for await (const p of computrabajo.search(TERM, {
			client,
			since: new Date('2000-01-01'),
			location: LOCATION,
			recordPage: (entry) => logs.push(entry),
			resumePage
		})) {
			ids.push(p.externalId);
		}
	} catch (err) {
		error = err;
	}
	return { logs, ids, error, urls: client.urls };
}

describe('búsqueda con bitácora de páginas', () => {
	// El adapter recorre dos lugares por palabra: remoto y la ciudad (bogota). Los handlers
	// cubren ambos; la ciudad se arma con total chico para cortar en la primera página.
	const handlersFor = (
		remote: Record<number, (url: string) => string>,
		city: Record<number, (url: string) => string> = { 1: () => pageHtml(5, '-city') }
	) => {
		const map: Record<string, (url: string) => string> = {};
		for (const [page, fn] of Object.entries(remote)) map[`remoto:${page}`] = fn;
		for (const [page, fn] of Object.entries(city)) map[`bogota:${page}`] = fn;
		return map;
	};

	test('cada página pedida deja una fila con lugar, página, resultado y vacantes parseadas', async () => {
		// 3 páginas (total 50 = 20+20+10); la 3ª llega al tope y corta por sin-paginas
		const html = (n: number) => pageHtml(50, `-p${n}`);
		const client = fakeClient(handlersFor({ 1: () => html(1), 2: () => html(2), 3: () => html(3) }));
		const { logs, error, urls } = await runSearch(client);

		expect(error).toBeUndefined();
		expect(urls.filter((u) => placeOf(u) === 'remoto').map((u) => pageOf(u))).toEqual([1, 2, 3]);
		const remote = logs.filter((l) => l.place === 'remoto');
		expect(remote.map((l) => [l.page, l.outcome, l.parsed])).toEqual([
			[1, 'ok', 10],
			[2, 'ok', 10],
			[3, 'sin-paginas', 10]
		]);
		expect(remote[0].placeLabel).toBe('remoto (todo el país)');
		// el segundo lugar también deja su fila y su etiqueta legible
		const cityLog = logs.find((l) => l.place === 'bogota');
		expect(cityLog).toMatchObject({ page: 1, outcome: 'sin-paginas', parsed: 10 });
		expect(cityLog?.placeLabel).toBe('bogota');
	});

	test('una página sin novedades corta con el resultado sin-novedades', async () => {
		// con un since futuro ninguna tarjeta cuenta como reciente, aunque la página traiga 10
		const client = fakeClient(handlersFor({ 1: () => pageHtml(50, '-nuevo') }));
		const logs: PageLogEntry[] = [];
		const gen = computrabajo.search(TERM, {
			client,
			since: new Date('2030-01-01'),
			location: LOCATION,
			recordPage: (e) => logs.push(e)
		});
		// eslint-disable-next-line @typescript-eslint/no-unused-vars
		for await (const _ of gen) {
			// todas se descartan por fecha: el generador no entrega vacantes
		}
		expect(logs[0]).toMatchObject({ place: 'remoto', page: 1, outcome: 'sin-novedades', parsed: 10 });
		expect(logs.every((l) => l.outcome === 'sin-novedades')).toBe(true);
	});

	test('BlockedError en la página 2: fila bloqueado, se relanza y lo ya entregado se conserva', async () => {
		const client = fakeClient(
			handlersFor({
				1: () => pageHtml(50, '-p1'),
				2: () => {
					throw new BlockedError('HTTP 429 en la página 2');
				}
			})
		);
		const { logs, ids, error, urls } = await runSearch(client);

		expect(error).toBeInstanceOf(BlockedError);
		expect(urls.map((u) => pageOf(u))).toEqual([1, 2]);
		expect(logs).toHaveLength(2);
		expect(logs[0]).toMatchObject({ place: 'remoto', page: 1, outcome: 'ok', parsed: 10 });
		expect(logs[1]).toMatchObject({ place: 'remoto', page: 2, outcome: 'bloqueado', parsed: 0 });
		expect(logs[1].error).toContain('429');
		// la página 1 parseó 10 tarjetas; tras el filtro de ubicación se entregaron 8, y todas
		// salieron del generador antes del fallo (no se pierden)
		expect(ids).toHaveLength(8);
		expect(new Set(ids).size).toBe(8);
		// al fallar el lugar remoto, la ciudad ni se alcanza a pedir
		expect(urls.some((u) => placeOf(u) === 'bogota')).toBe(false);
	});

	test('un error común en la página 2 queda como error, no como bloqueo', async () => {
		const client = fakeClient(
			handlersFor({
				1: () => pageHtml(50, '-p1'),
				2: () => {
					throw new Error('fallo de red');
				}
			})
		);
		const { logs, ids, error } = await runSearch(client);

		expect(error).not.toBeInstanceOf(BlockedError);
		expect(logs[1]).toMatchObject({ page: 2, outcome: 'error', parsed: 0 });
		expect(logs[1].error).toBe('fallo de red');
		expect(ids).toHaveLength(8); // la página 1 entregó sus 8 vacantes filtradas: no se pierden
	});

	test('el cupo agotado también se registra como falla de página', async () => {
		const client = fakeClient(
			handlersFor({
				1: () => pageHtml(50, '-p1'),
				2: () => {
					throw new BudgetExhaustedError('cupo alcanzado');
				}
			})
		);
		const { logs, error } = await runSearch(client);
		expect(error).toBeInstanceOf(BudgetExhaustedError);
		expect(logs[1]).toMatchObject({ page: 2, outcome: 'error', parsed: 0 });
	});

	test('reanudación: si la última fila fue un fallo, arranca por esa página; si terminó bien, por la 1', async () => {
		// escenario A: la bitácora dice que la página 2 falló → se reintenta la 2 (no la 1)
		const resume = (_term: string, place: string) => (place === 'remoto' ? 2 : 1);
		const client = fakeClient(
			handlersFor(
				{ 2: () => pageHtml(50, '-p2'), 3: () => pageHtml(50, '-p3') },
				{ 1: () => pageHtml(5, '-city') }
			)
		);
		const { urls, logs } = await runSearch(client, resume);

		expect(urls.filter((u) => placeOf(u) === 'remoto').map((u) => pageOf(u))).toEqual([2, 3]);
		expect(logs.find((l) => l.place === 'remoto' && l.page === 3)?.outcome).toBe('sin-paginas');

		// escenario B: sin fallo previo (resumePage devuelve 1) → siempre desde la página 1
		const clientFresh = fakeClient(handlersFor({ 1: () => pageHtml(10, '-p1') }));
		const fresh = await runSearch(clientFresh, () => 1);
		expect(fresh.urls.filter((u) => placeOf(u) === 'remoto').map((u) => pageOf(u))).toEqual([1]);
	});

	test('sin los hooks, el adapter funciona igual que antes (arranca en página 1)', async () => {
		const client = fakeClient(handlersFor({ 1: () => pageHtml(10, '-p1') }));
		const ids: string[] = [];
		for await (const p of computrabajo.search(TERM, {
			client,
			since: new Date('2000-01-01'),
			location: LOCATION
		})) {
			ids.push(p.externalId);
		}
		expect(ids.length).toBeGreaterThan(0);
		expect(client.urls.filter((u) => placeOf(u) === 'remoto').map((u) => pageOf(u))).toEqual([1]);
	});
});
