import { describe, expect, test } from 'bun:test';
import { sameVacancies, type Posting } from './same-vacancy';

// textos de 100 palabras: `retouched` cambia 1 de cada 20 (≈ 0,73 de texto compartido)
const words = (seed: string) => Array.from({ length: 100 }, (_, i) => `${seed}${i}`);
const text = (seed: string) => words(seed).join(' ');
const retouched = (seed: string) => words(seed).map((w, i) => (i % 20 === 5 ? `cambio${i}` : w)).join(' ');

const DAY = 86_400_000;
let nextId = 1;
const posting = (title: string, description: string | null, day: number, status = 'nueva'): Posting => ({
	id: nextId++,
	companyId: null,
	title,
	normalizedTitle: title.toLowerCase(),
	description,
	status,
	dates: [Date.UTC(2026, 6, 1) + day * DAY]
});
const groups = (postings: Posting[], confidential = false) =>
	sameVacancies(postings, { confidential }).map((v) => v.postings.map((p) => p.title).join(' + '));

describe('sameVacancies', () => {
	test('en una empresa, el mismo título basta', () => {
		expect(groups([posting('Backend', text('a'), 0), posting('Backend', text('b'), 30)])).toEqual(['Backend + Backend']);
	});

	test('entre confidenciales, el mismo título con otra descripción son vacantes distintas', () => {
		expect(groups([posting('Backend', text('a'), 0), posting('Backend', text('b'), 30)], true)).toEqual([
			'Backend',
			'Backend'
		]);
	});

	test('entre confidenciales, el mismo título con la descripción retocada es la misma', () => {
		expect(groups([posting('Backend', text('a'), 0), posting('Backend', retouched('a'), 30)], true)).toEqual([
			'Backend + Backend'
		]);
	});

	test('entre confidenciales, sin descripción no se agrupan', () => {
		expect(groups([posting('Backend', null, 0), posting('Backend', null, 30)], true)).toHaveLength(2);
	});

	test('la descripción casi idéntica agrupa aunque cambie el título', () => {
		expect(groups([posting('Backend', text('a'), 0), posting('Dev Backend', text('a'), 30)], true)).toEqual([
			'Backend + Dev Backend'
		]);
	});

	test('con tu descarte basta una descripción muy parecida', () => {
		const pair = [posting('Backend', text('a'), 0), posting('Dev Node', retouched('a'), 30)];
		expect(groups(pair, true)).toHaveLength(2);
		pair[1].status = 'descartada';
		expect(groups(pair, true)).toEqual(['Backend + Dev Node']);
	});

	test('publicaciones a menos de 7 días cuentan como una', () => {
		const [v] = sameVacancies([posting('Backend', text('a'), 0), posting('Backend', text('a'), 6), posting('Backend', text('a'), 40)]);
		expect(v.dates).toHaveLength(2);
	});
});
