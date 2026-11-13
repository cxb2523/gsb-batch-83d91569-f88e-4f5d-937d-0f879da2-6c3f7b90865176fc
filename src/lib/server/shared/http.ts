const HEADERS = {
	'User-Agent':
		'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
	'Accept-Language': 'es-CO,es;q=0.9,en;q=0.5'
};

/** La plataforma nos frenó (429/403/451/999, captcha, muro de login): hay que dejarla en pausa. */
export class BlockedError extends Error {}

/**
 * Hay que dejar de pedir en esta búsqueda, sin que sea un bloqueo: se acabó el cupo, o el sitio
 * avisó un límite (429) y conviene no insistir. Lo que falta sigue la próxima vez.
 */
export class BudgetExhaustedError extends Error {}

/** Respuesta con error que no es un bloqueo (404, 410, 5xx después de los reintentos…). */
export class HttpError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
	}
}

export type ClientOptions = {
	/** Guardar y devolver las cookies de la sesión anónima (por defecto, sí). */
	cookies?: boolean;
	/** Ante un 429, esperar esto (ms) y reintentar una sola vez antes de rendirse. */
	blockRetryMs?: number;
	/** Se llama al recibir un 429, para dejarlo registrado aunque el proceso se corte en la espera. */
	onRateLimit?: () => void;
	/** Tope duro de peticiones (incluidos los reintentos): al llegar, `BudgetExhaustedError`. */
	maxRequests?: number;
	/** No seguir redirecciones: cualquier 3xx cuenta como bloqueo (LinkedIn manda al muro de login). */
	blockRedirects?: boolean;
};

export type HttpClient = {
	text(url: string, init?: RequestInit): Promise<string>;
	json<T>(url: string, init?: RequestInit): Promise<T>;
	/** Peticiones hechas con este cliente (para el cupo por corrida). */
	requests(): number;
	/** Si el sitio avisó un límite (429) durante esta búsqueda. */
	rateLimited(): boolean;
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const BLOCKED_STATUS = new Set([403, 429, 451, 999]); // 999: la respuesta propia de LinkedIn
// adonde redirigen los sitios cuando no quieren servir a un visitante sin sesión
const LOGIN_WALL = /authwall|\/login|\/signup|checkpoint|\/uas\//i;

// Un desafío de captcha es una página corta; un sitio normal puede traer un formulario con
// reCAPTCHA en una página grande (elempleo) sin que eso sea un bloqueo.
const CHALLENGE_PAGE_MAX = 20_000;

/** ¿La respuesta es una página de desafío en vez del contenido? */
export function isChallengePage(body: string): boolean {
	if (/cf-chl|challenge-platform/i.test(body)) return true;
	return body.length < CHALLENGE_PAGE_MAX && /g-recaptcha|hcaptcha/i.test(body);
}

/**
 * Cliente por plataforma: una petición a la vez, con una pausa aleatoria entre el final de
 * una respuesta y la siguiente petición, y reintentos solo para errores de red o 5xx. Guarda
 * las cookies de la sesión anónima que mande el sitio durante la misma corrida.
 */
export function createClient(delay: { min: number; max: number }, options: ClientOptions = {}): HttpClient {
	let last = 0;
	let count = 0;
	let rateLimited = false;
	const cookies = new Map<string, string>();
	const keepCookies = options.cookies ?? true;

	async function request(url: string, init: RequestInit = {}): Promise<Response> {
		// después de un 429 (aunque el reintento haya salido bien) no se insiste en esta búsqueda
		if (rateLimited) throw new BudgetExhaustedError('El sitio avisó un límite (429): se corta la búsqueda');

		for (let attempt = 1; ; attempt++) {
			if (options.maxRequests !== undefined && count >= options.maxRequests) {
				throw new BudgetExhaustedError(`Cupo de ${options.maxRequests} peticiones alcanzado`);
			}
			const wait = last + delay.min + Math.random() * (delay.max - delay.min) - Date.now();
			if (last && wait > 0) await sleep(wait);
			count++;
			try {
				const cookie = [...cookies].map(([name, value]) => `${name}=${value}`).join('; ');
				const res = await fetch(url, {
					...init,
					redirect: options.blockRedirects ? 'manual' : 'follow',
					headers: { ...HEADERS, ...(cookie ? { Cookie: cookie } : {}), ...init.headers },
					signal: AbortSignal.timeout(30_000)
				});
				last = Date.now();
				for (const header of keepCookies ? res.headers.getSetCookie() : []) {
					const [pair] = header.split(';');
					const eq = pair.indexOf('=');
					if (eq > 0) cookies.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
				}
				if (options.blockRedirects && res.status >= 300 && res.status < 400) {
					throw new BlockedError(`Redirección (${res.status}) a ${res.headers.get('location') ?? '?'} en ${url}`);
				}
				if (res.redirected && LOGIN_WALL.test(res.url)) {
					throw new BlockedError(`Redirigido al muro de login (${res.url}) en ${url}`);
				}
				if (res.status === 429 && options.blockRetryMs && !rateLimited) {
					// un 429 suele ser una ráfaga que se limpia sola: una espera y un solo reintento
					// por búsqueda, para terminar lo que estaba en curso
					rateLimited = true;
					options.onRateLimit?.();
					await sleep(options.blockRetryMs);
					continue;
				}
				if (res.status === 429) {
					rateLimited = true;
					options.onRateLimit?.();
				}
				if (BLOCKED_STATUS.has(res.status)) throw new BlockedError(`HTTP ${res.status} en ${url}`);
				if (res.status >= 500 && attempt < 3) {
					await sleep(attempt * 5_000);
					continue;
				}
				if (!res.ok) throw new HttpError(`HTTP ${res.status} en ${url}`, res.status);
				return res;
			} catch (err) {
				last = Date.now();
				// solo se reintentan errores de red y timeouts
				if (err instanceof BlockedError || err instanceof HttpError || attempt >= 3) throw err;
				await sleep(attempt * 5_000);
			}
		}
	}

	return {
		async text(url, init) {
			const body = await (await request(url, init)).text();
			if (isChallengePage(body)) throw new BlockedError(`Captcha en ${url}`);
			return body;
		},
		async json(url, init) {
			return (await request(url, init)).json();
		},
		requests: () => count,
		rateLimited: () => rateLimited
	};
}
