import { describe, expect, test } from 'bun:test';
import { parsePublishedDate } from './relative-date';

const NOW = new Date('2026-10-14T20:00:00Z');
const day = (text: string) => parsePublishedDate(text, NOW)?.date.toISOString().slice(0, 10);

describe('parsePublishedDate', () => {
	test('relativas', () => {
		expect(day('Hace 1 hora')).toBe('2026-10-14');
		expect(day('Hace  13  horas')).toBe('2026-10-14');
		expect(day('Ayer')).toBe('2026-10-13');
		expect(day('Hace 5 días')).toBe('2026-10-09');
		expect(day('Hace 2 semanas')).toBe('2026-09-30');
		expect(day('Hoy')).toBe('2026-10-14');
	});

	test('absolutas, con y sin año', () => {
		expect(day('14 de septiembre')).toBe('2026-09-14');
		expect(day('1 de octubre')).toBe('2026-10-01');
		// sin año y en el futuro: es del año pasado
		expect(day('20 de diciembre')).toBe('2025-12-20');
		expect(day('3 de marzo de 2025')).toBe('2025-03-03');
	});

	test('"Más de 30 días" es solo un tope', () => {
		expect(parsePublishedDate('Más de 30 días', NOW)).toEqual({
			date: new Date('2026-09-14T12:00:00Z'),
			approximate: true
		});
		expect(parsePublishedDate('Hace 30 días', NOW)?.approximate).toBe(false);
	});

	test('lo que no entiende devuelve null', () => {
		expect(parsePublishedDate('publicada', NOW)).toBeNull();
		expect(parsePublishedDate('30 de brumario', NOW)).toBeNull();
	});
});
