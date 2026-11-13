import { describe, expect, test } from 'bun:test';
import { detectLanguage } from './language';

describe('detectLanguage', () => {
	test('español', () => {
		expect(
			detectLanguage(
				'Buscamos un Desarrollador Full Stack con experiencia en React y Node.js para trabajar en el equipo de producto. Requisitos: 3 años de experiencia con TypeScript y conocimientos de AWS.'
			)
		).toBe('es');
	});

	test('inglés', () => {
		expect(
			detectLanguage(
				'We are looking for a Senior Full Stack Developer to join our team. You will work with React and Node.js. Requirements: 5+ years of experience with TypeScript and strong skills in AWS.'
			)
		).toBe('en');
	});

	test('muy corto o mezclado: no decide', () => {
		expect(detectLanguage('Full Stack Developer React Node.js')).toBeNull();
	});
});
