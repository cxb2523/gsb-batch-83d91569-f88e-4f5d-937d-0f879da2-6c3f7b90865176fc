import { describe, expect, test } from 'bun:test';
import { dueKeywords, gapUntil } from './throttle';

const NOW = Date.parse('2026-10-22T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

describe('gapUntil', () => {
	test('corrida reciente: espera hasta cumplir el intervalo', () => {
		expect(gapUntil(new Date(NOW - 10 * 60_000).toISOString(), 30, NOW)).toBe('2026-10-22T12:20:00.000Z');
	});

	test('corrida vieja, sin corridas o sin intervalo: no espera', () => {
		expect(gapUntil(hoursAgo(1), 30, NOW)).toBeNull();
		expect(gapUntil(null, 30, NOW)).toBeNull();
		expect(gapUntil(hoursAgo(0), undefined, NOW)).toBeNull();
	});
});

describe('dueKeywords', () => {
	const keywords = [{ term: 'fullstack' }, { term: 'typescript' }, { term: 'devops' }];

	test('tocan las nunca buscadas y las de hace más de una semana', () => {
		const cursors = new Map([
			['fullstack', hoursAgo(24)],
			['typescript', hoursAgo(200)]
		]);
		expect(dueKeywords(keywords, cursors, 168, NOW).due.map((k) => k.term)).toEqual(['typescript', 'devops']);
	});

	test('todas buscadas esta semana: ninguna toca y dice cuándo vuelve la primera', () => {
		const cursors = new Map(keywords.map((k, i) => [k.term, hoursAgo(10 + i)]));
		const { due, nextAt } = dueKeywords(keywords, cursors, 168, NOW);
		expect(due).toEqual([]);
		expect(nextAt).toBe(new Date(NOW + (168 - 12) * 3_600_000).toISOString());
	});

	test('sin intervalo configurado: tocan todas', () => {
		expect(dueKeywords(keywords, new Map([['fullstack', hoursAgo(1)]]), undefined, NOW).due).toHaveLength(3);
	});

	test('sin palabras clave: no falla', () => {
		expect(dueKeywords([], new Map(), 168, NOW)).toEqual({ due: [], nextAt: null });
	});
});
