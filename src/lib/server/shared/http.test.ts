import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { BlockedError, BudgetExhaustedError, createClient, isChallengePage } from './http';

describe('isChallengePage', () => {
	test('un desafío de Cloudflare siempre es bloqueo', () => {
		expect(isChallengePage('<html>' + 'x'.repeat(50_000) + 'challenge-platform</html>')).toBe(true);
	});

	test('una página corta con captcha es un desafío', () => {
		expect(isChallengePage('<html><div class="g-recaptcha"></div></html>')).toBe(true);
	});

	test('una página real con un formulario de reCAPTCHA no es bloqueo', () => {
		const page = readFileSync(resolve('fixtures/elempleo/portada-ofertas.html'), 'utf8');
		expect(page).toContain('g-recaptcha');
		expect(isChallengePage(page)).toBe(false);
	});
});

describe('createClient', () => {
	const realFetch = globalThis.fetch;
	const respond = (statuses: number[], seen: Headers[] = []) => {
		let i = 0;
		globalThis.fetch = (async (_url: string, init: RequestInit) => {
			seen.push(new Headers(init.headers));
			const status = statuses[Math.min(i++, statuses.length - 1)];
			const headers: Record<string, string> = { 'set-cookie': 'session=abc; Path=/' };
			if (status >= 300 && status < 400) headers.location = 'https://www.linkedin.com/authwall?trk=x';
			return new Response(status >= 300 && status < 400 ? null : 'ok', { status, headers });
		}) as typeof fetch;
	};
	const restore = () => (globalThis.fetch = realFetch);

	test('un 429 con reintento configurado: espera y reintenta una sola vez', async () => {
		respond([429, 200]);
		const client = createClient({ min: 0, max: 0 }, { blockRetryMs: 1 });
		expect(await client.text('https://x.test/a')).toBe('ok');
		expect(client.requests()).toBe(2);
		restore();
	});

	test('si el reintento también da 429, la plataforma queda bloqueada', async () => {
		respond([429, 429]);
		const client = createClient({ min: 0, max: 0 }, { blockRetryMs: 1 });
		await expect(client.text('https://x.test/a')).rejects.toBeInstanceOf(BlockedError);
		expect(client.requests()).toBe(2);
		restore();
	});

	test('sin reintento configurado, el primer 429 bloquea', async () => {
		respond([429]);
		const client = createClient({ min: 0, max: 0 });
		await expect(client.text('https://x.test/a')).rejects.toBeInstanceOf(BlockedError);
		expect(client.requests()).toBe(1);
		restore();
	});

	test('devuelve las cookies de la sesión salvo que se desactiven', async () => {
		const withCookies: Headers[] = [];
		respond([200], withCookies);
		const a = createClient({ min: 0, max: 0 });
		await a.text('https://x.test/1');
		await a.text('https://x.test/2');
		expect(withCookies[1].get('cookie')).toBe('session=abc');

		const without: Headers[] = [];
		respond([200], without);
		const b = createClient({ min: 0, max: 0 }, { cookies: false });
		await b.text('https://x.test/1');
		await b.text('https://x.test/2');
		expect(without[1].get('cookie')).toBeNull();
		restore();
	});

	test('después de un 429, aunque el reintento salga bien, la búsqueda se corta', async () => {
		respond([429, 200, 200]);
		let noted = 0;
		const client = createClient({ min: 0, max: 0 }, { blockRetryMs: 1, onRateLimit: () => noted++ });
		expect(await client.text('https://x.test/a')).toBe('ok');
		expect(noted).toBe(1);
		expect(client.rateLimited()).toBe(true);
		await expect(client.text('https://x.test/b')).rejects.toBeInstanceOf(BudgetExhaustedError);
		expect(client.requests()).toBe(2);
		restore();
	});

	test('el cupo es un tope duro, incluidos los reintentos', async () => {
		respond([200]);
		const client = createClient({ min: 0, max: 0 }, { maxRequests: 2 });
		await client.text('https://x.test/1');
		await client.text('https://x.test/2');
		await expect(client.text('https://x.test/3')).rejects.toBeInstanceOf(BudgetExhaustedError);
		expect(client.requests()).toBe(2);
		restore();
	});

	test('una redirección (muro de login) cuenta como bloqueo si no se siguen', async () => {
		respond([302]);
		const client = createClient({ min: 0, max: 0 }, { blockRedirects: true });
		await expect(client.text('https://x.test/a')).rejects.toThrow(/authwall/);
		restore();
	});

	test('451 cuenta como bloqueo', async () => {
		respond([451]);
		await expect(createClient({ min: 0, max: 0 }).text('https://x.test/a')).rejects.toBeInstanceOf(BlockedError);
		restore();
	});

	test('999 (LinkedIn) cuenta como bloqueo', async () => {
		// `new Response` no acepta estados fuera de 200–599; el fetch real sí entrega un 999
		globalThis.fetch = (async () =>
			({ status: 999, ok: false, redirected: false, url: 'https://x.test/a', headers: new Headers() }) as Response) as unknown as typeof fetch;
		await expect(createClient({ min: 0, max: 0 }).text('https://x.test/a')).rejects.toBeInstanceOf(BlockedError);
		restore();
	});
});
