import { describe, expect, test } from 'bun:test';
import { pauseMinutesFor } from './pause';

describe('pauseMinutesFor', () => {
	test('cada bloqueo seguido sube un escalón y el último se repite', () => {
		const ladder = [15, 60, 240];
		expect([1, 2, 3, 4, 9].map((n) => pauseMinutesFor(n, ladder))).toEqual([15, 60, 240, 240, 240]);
	});

	test('por defecto: un día, dos, cuatro y una semana', () => {
		expect([1, 2, 3, 4, 5].map((n) => pauseMinutesFor(n))).toEqual([1_440, 2_880, 5_760, 10_080, 10_080]);
	});
});
