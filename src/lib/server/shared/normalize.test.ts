import { describe, expect, test } from 'bun:test';
import { mentionsTerm } from './normalize';

describe('mentionsTerm', () => {
	test('todas las palabras del término, sin tildes ni mayúsculas', () => {
		expect(mentionsTerm('Buscamos Tech Lead con experiencia', 'tech lead')).toBe(true);
		expect(mentionsTerm('Líder Técnico de Instalaciones', 'tech lead')).toBe(false);
		expect(mentionsTerm('Ingeniero de Software Senior', 'ingeniero de software')).toBe(true);
		expect(mentionsTerm('Desarrollador comercial TAT', 'desarrollador web')).toBe(false);
	});

	test('acepta plurales y términos con punto', () => {
		expect(mentionsTerm('Se buscan desarrolladores backend', 'desarrollador backend')).toBe(true);
		expect(mentionsTerm('Experiencia en Node.js y AWS.', 'node.js')).toBe(true);
		expect(mentionsTerm('Experiencia en .NET Core', 'desarrollador .net')).toBe(false);
		expect(mentionsTerm('Desarrollador .NET Core', 'desarrollador .net')).toBe(true);
	});

	test('full stack, back end y front end escritos de cualquier forma', () => {
		expect(mentionsTerm('Back End Developer', 'backend developer')).toBe(true);
		expect(mentionsTerm('Desarrollador Full-Stack', 'desarrollador fullstack')).toBe(true);
		expect(mentionsTerm('Fullstack Developer', 'full stack developer')).toBe(true);
	});

	test('las palabras van en orden y cerca', () => {
		expect(mentionsTerm('Desarrollador Senior Backend', 'desarrollador backend')).toBe(true);
		expect(mentionsTerm('Forceget is a tech-driven company. Partner with the sales lead', 'tech lead')).toBe(false);
		expect(mentionsTerm('tecnico, tech, technician, technology, jefe, gerente, chief, lead', 'tech lead')).toBe(false);
		expect(mentionsTerm('Backend developer', 'developer backend')).toBe(false);
	});

	test('no confunde palabras que se contienen', () => {
		expect(mentionsTerm('Desarrollador JavaScript', 'java')).toBe(false);
		expect(mentionsTerm('Desarrollador Java', 'java')).toBe(true);
	});
});
