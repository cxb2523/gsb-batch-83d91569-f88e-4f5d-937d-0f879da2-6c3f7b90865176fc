import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseDetail, parseSearchPage, siteFor, slug } from './computrabajo';

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
