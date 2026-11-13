import { decodeEntities, htmlToText, normalizeText, samePlace } from '$lib/server/shared/normalize';
import type { Location } from '$lib/server/shared/profile';
import { parsePublishedDate } from '$lib/server/shared/relative-date';
import { BlockedError } from '$lib/server/shared/http';
import type { Modality, PageLogEntry, PlatformAdapter, RawPosting } from './types';

// Páginas HTML renderizadas en el servidor, sin login. Un subdominio por país, con el
// mismo formato: https://co.computrabajo.com/trabajo-de-<término>-en-<lugar>?by=publicationtime&p=N
const SUBDOMAINS: Record<string, string> = {
	colombia: 'co',
	mexico: 'mx',
	peru: 'pe',
	argentina: 'ar',
	chile: 'cl',
	ecuador: 'ec',
	venezuela: 've',
	bolivia: 'bo',
	paraguay: 'py',
	uruguay: 'uy',
	guatemala: 'gt',
	'el salvador': 'sv',
	honduras: 'hn',
	nicaragua: 'ni',
	'costa rica': 'cr',
	panama: 'pa',
	'republica dominicana': 'do'
};

const PER_PAGE = 20;
const MAX_PAGES = 15;
const DAY = 86_400_000;
// valores que acepta el filtro de fecha del sitio (días)
const PUBDATE_STEPS = [1, 3, 7, 15, 30];

export function siteFor(country: string): string | null {
	const sub = SUBDOMAINS[normalizeText(country)];
	return sub ? `https://${sub}.computrabajo.com` : null;
}

/** "Desarrollador .NET" → "desarrollador-net", como arma las URLs el sitio. */
export function slug(text: string): string {
	return normalizeText(text)
		.replace(/[^a-z0-9#+]+/g, '-')
		.replace(/^-+|-+$/g, '');
}

const clean = (html: string) => decodeEntities(html.replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ').trim();

export function parseSearchPage(html: string, origin: string, now = new Date()): { postings: RawPosting[]; total: number } {
	const total = Number(html.match(/<h1 class="title_page"[^>]*>\s*<span class="fwB">\s*([\d.]+)/)?.[1].replace(/\./g, '') ?? 0);
	const postings: RawPosting[] = [];

	for (const card of html.match(/<article class="box_offer[\s\S]*?<\/article>/g) ?? []) {
		const id = card.match(/data-id='(\w+)'/)?.[1];
		const link = card.match(/<a class="js-o-link[^"]*" href="([^"]+)">([\s\S]*?)<\/a>/);
		if (!id || !link) continue;

		// Con link a su perfil = empresa; sin link = confidencial ("Importante empresa del sector")
		const companyLink = card.match(/offer-grid-article-company-url>([\s\S]*?)<\/a>/);
		const companyText = card.match(/<p class="dFlex vm_fx fs16 fc_base mt5">([\s\S]*?)<\/p>/);
		const location = card.match(/<p class="fs16 fc_base mt5">\s*<span class="mr10">([\s\S]*?)<\/span>/);
		const tags = [...card.matchAll(/<span class="dIB mr10">([\s\S]*?)<\/span>\s*(?=<span|<\/div>)/g)].map((m) => clean(m[1]));
		const dateText = clean(card.match(/<p class="fs13 fc_aux mt15">([\s\S]*?)<\/p>/)?.[1] ?? '');

		const published = parsePublishedDate(dateText, now);

		const modality: Modality = tags.includes('Presencial y remoto')
			? 'hibrido'
			: tags.includes('Remoto')
				? 'remoto'
				: 'presencial';

		// el href trae entidades (tildes como &#xED;) y un ancla de seguimiento (#lc=...)
		const url = new URL(decodeEntities(link[1]), origin);
		url.hash = '';

		postings.push({
			externalId: id,
			url: url.href,
			title: clean(link[2]),
			company: companyLink ? clean(companyLink[1]) : null,
			recruiter: !companyLink && companyText ? clean(companyText[1]) : undefined,
			location: location ? clean(location[1]) : undefined,
			modality,
			publishedAt: published?.date ?? now,
			publishedRaw: dateText,
			publishedApprox: !published || published.approximate || undefined
		});
	}
	return { postings, total };
}

/** La descripción completa, con requisitos y conocimientos, desde la página de la vacante. */
export function parseDetail(html: string): Partial<RawPosting> {
	const start = html.indexOf('Descripción de la oferta</h2>');
	if (start < 0) return {};
	const ends = ['Aptitudes asociadas', 'div-link="empresa"']
		.map((marker) => html.indexOf(marker, start))
		.filter((i) => i > 0);
	const block = html.slice(start + 'Descripción de la oferta</h2>'.length, ends.length ? Math.min(...ends) : start + 20_000);
	const description = htmlToText(block);
	return description ? { description } : {};
}

/** Remoto en el país del sitio, o presencial/híbrido en tu ciudad (o sin ciudad: todo el país). */
function wanted(p: RawPosting, where: Location): boolean {
	if (p.modality === 'remoto') return true;
	const place = p.location ?? '';
	return samePlace(place, where.city) || normalizeText(place) === normalizeText(where.country);
}

/** El filtro de fecha más chico que cubra desde `since`; sin filtro si son más de 30 días. */
function pubdate(since: Date): number | null {
	const days = Math.ceil((Date.now() - since.getTime()) / DAY);
	return PUBDATE_STEPS.find((d) => d >= days) ?? null;
}

/**
 * Los dos lugares que se buscan por cada palabra: las remotas de todo el país y las de tu
 * ciudad (sin ciudad configurada, el slug queda vacío y la URL cubre todo el país).
 */
export function placesFor(location: Location): { place: string; label: string }[] {
	const city = slug(location.city);
	return [
		{ place: 'remoto', label: 'remoto (todo el país)' },
		{ place: city, label: city || 'todo el país' }
	];
}

function pageUrl(origin: string, term: string, place: string, days: number | null, page: number): string {
	const params = new URLSearchParams({ by: 'publicationtime' });
	if (days) params.set('pubdate', String(days));
	if (page > 1) params.set('p', String(page));
	return `${origin}/trabajo-de-${encodeURIComponent(slug(term))}-en-${place}?${params}`;
}

export const computrabajo: PlatformAdapter = {
	id: 'computrabajo',
	name: 'Computrabajo',
	delay: { min: 3_000, max: 7_000 },
	looseSearch: true,

	async *search(term, ctx) {
		const { client, since, location } = ctx;
		const origin = siteFor(location.country);
		if (!origin) throw new Error(`Computrabajo no tiene sitio para "${location.country}"`);

		const days = pubdate(since);
		// dos búsquedas por palabra: remotas de todo el país y las de tu ciudad
		for (const { place, label } of placesFor(location)) {
			// si la última vez esta palabra/lugar se cortó en una página, se reintenta esa misma;
			// si terminó bien (o nunca se buscó), se arranca por la 1 con el cursor normal
			let page = ctx.resumePage?.(term, place) ?? 1;
			while (page <= MAX_PAGES) {
				const url = pageUrl(origin, term, place, days, page);
				let parsed = 0;
				try {
					const { postings, total } = parseSearchPage(await client.text(url), origin);
					parsed = postings.length;
					// el orden por fecha no es estricto: se corta cuando la página no trae nada reciente
					// con fecha cierta ("Más de 30 días" no cuenta como reciente)
					let recent = false;
					for (const p of postings) {
						if (p.publishedAt < since) continue;
						if (!p.publishedApprox) recent = true;
						if (wanted(p, location)) yield p;
					}
					// se guarda la página antes de seguir: las vacantes ya entregadas no se pierden
					// aunque la próxima página falle
					if (!recent) {
						logPage(ctx, { place, placeLabel: label, page, outcome: 'sin-novedades', parsed });
						break;
					}
					if (page * PER_PAGE >= total) {
						logPage(ctx, { place, placeLabel: label, page, outcome: 'sin-paginas', parsed });
						break;
					}
					logPage(ctx, { place, placeLabel: label, page, outcome: 'ok', parsed });
					page++;
				} catch (err) {
					// la página fallida queda registrada y se relanza: la plataforma se pausa y la
					// próxima búsqueda reintenta esta misma página, no la 1
					const blocked = err instanceof BlockedError;
					logPage(ctx, {
						place,
						placeLabel: label,
						page,
						outcome: blocked ? 'bloqueado' : 'error',
						parsed,
						error: err instanceof Error ? err.message : String(err)
					});
					throw err;
				}
			}
		}
	},

	async fetchDetail(posting, { client }) {
		return parseDetail(await client.text(posting.url));
	}
};

/** Escribe la fila de la bitácora si el contexto trajo el hook (la app real lo trae). */
function logPage(ctx: { recordPage?: (entry: PageLogEntry) => void }, entry: PageLogEntry): void {
	ctx.recordPage?.(entry);
}
