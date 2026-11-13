import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseLanding, toPosting, type Offer } from './elempleo';

const fixture = (name: string) => readFileSync(resolve('fixtures/elempleo', name), 'utf8');
const offers: Offer[] = JSON.parse(fixture('api-busqueda.json')).results;
const byId = (id: number) => toPosting(offers.find((o) => o.id === id)!);

describe('parseLanding', () => {
	const session = parseLanding(fixture('portada-ofertas.html'));

	test('saca el token de la búsqueda', () => {
		expect(session.token.length).toBeGreaterThan(100);
	});

	test('saca el id de cada ciudad', () => {
		expect(session.cityIds.get('barranquilla')).toBe(2);
		expect(session.cityIds.get('bogota')).toBe(34);
	});

	test('sin token avisa en vez de seguir', () => {
		expect(() => parseLanding('<html></html>')).toThrow('token');
	});
});

describe('toPosting', () => {
	test('arma la vacante desde la API', () => {
		expect(byId(1886767913)).toMatchObject({
			externalId: '1886767913',
			url: 'https://www.elempleo.com/co/ofertas-trabajo/desarrollador-fullstack-net-angular-sql-server-bogota-presencial-1886767913',
			title: 'Desarrollador fullstack .Net + Angular + SQL Server - Bogotá presencial',
			company: 'TALYCAP GLOBAL SAS',
			location: 'Bogotá',
			modality: 'presencial',
			publishedRaw: 'Hace 1 mes'
		});
		expect(byId(1886767913).publishedAt.toISOString()).toBe('2026-09-16T12:00:00.000Z');
	});

	test('modalidad remota e híbrida', () => {
		expect(byId(1886781918).modality).toBe('remoto');
		expect(byId(1886781025).modality).toBe('hibrido');
	});

	test('una empresa confidencial no se guarda como empresa', () => {
		const p = byId(1886712686);
		expect(p.company).toBeNull();
		expect(p.recruiter).toBe('Empresa confidencial');
	});

	test('la descripción queda en texto plano', () => {
		for (const o of offers) expect(toPosting(o).description ?? '').not.toMatch(/<[a-z]/i);
	});
});
