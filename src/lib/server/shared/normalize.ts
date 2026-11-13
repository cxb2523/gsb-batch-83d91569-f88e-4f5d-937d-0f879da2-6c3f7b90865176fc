import { createHash } from 'node:crypto';

/** Minúsculas, sin tildes, sin signos; deja letras, números y + # . (c#, node.js). */
export function normalizeText(text: string): string {
	return text
		.normalize('NFD')
		.replace(/\p{Diacritic}/gu, '')
		.toLowerCase()
		.replace(/[^a-z0-9+#.]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

const COMPANY_SUFFIXES = /\b(s ?a ?s|s ?a|ltda|inc|llc|corp|spa|s ?de ?r ?l|sa de cv)\b\.?/g;

export function normalizeCompany(name: string): string {
	return normalizeText(name.replace(/\./g, ' ')).replace(COMPANY_SUFFIXES, '').replace(/\s+/g, ' ').trim();
}

// Palabras que cambian entre republicaciones sin que cambie la vacante.
const TITLE_NOISE =
	/\b(urgente|urgent|remoto|remote|hibrido|hybrid|presencial|colombia|latam|barranquilla|bogota|medellin|cali|100|a|o|as|os)\b/g;

/** "full stack" / "full-stack" → "fullstack", igual con backend y frontend. */
function joinCompounds(text: string): string {
	return text
		.replace(/\bfull ?stack\b/g, 'fullstack')
		.replace(/\bback ?end\b/g, 'backend')
		.replace(/\bfront ?end\b/g, 'frontend');
}

export function normalizeTitle(title: string): string {
	return joinCompounds(normalizeText(title))
		.replace(TITLE_NOISE, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

const NAMED_ENTITIES: Record<string, string> = { nbsp: ' ', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };

/** "Bogot&#xE1;" → "Bogotá". Numéricas (decimales y hex) y las nombradas más comunes. */
export function decodeEntities(text: string): string {
	return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, code: string) => {
		if (code[0] === '#') {
			const n = code[1] === 'x' || code[1] === 'X' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
			return Number.isNaN(n) ? entity : String.fromCodePoint(n);
		}
		return NAMED_ENTITIES[code.toLowerCase()] ?? entity;
	});
}

export function htmlToText(html: string): string {
	return decodeEntities(
		html
			.replace(/<(br|\/p|\/li|\/h\d)[^>]*>/gi, '\n')
			.replace(/<[^>]+>/g, ' ')
	)
		.replace(/[ \t]+/g, ' ')
		.replace(/\n\s*\n+/g, '\n')
		.trim();
}

export function descriptionHash(description: string): string {
	return createHash('sha1').update(normalizeText(description)).digest('hex');
}

/** "Barranquilla, Atlántico" contiene "barranquilla"; sin importar tildes ni mayúsculas. */
export function samePlace(text: string, place: string): boolean {
	return normalizeText(text).includes(normalizeText(place));
}

const TERM_STOPWORDS = new Set(['de', 'del', 'la', 'el', 'los', 'las', 'en', 'y', 'e', 'o', 'u', 'para', 'con', 'a']);

/**
 * ¿El texto menciona el término de búsqueda? Sus palabras tienen que aparecer en orden y
 * cerca (hasta 2 palabras entre una y otra): "desarrollador backend" coincide con
 * "Desarrollador Senior Backend", pero "tech lead" no con "tech-driven… sales lead".
 * Sin tildes ni mayúsculas, ignorando "de", "en"… y aceptando plurales.
 */
export function mentionsTerm(text: string, term: string): boolean {
	const words = joinCompounds(normalizeText(term))
		.split(' ')
		.filter((w) => w && !TERM_STOPWORDS.has(w))
		.map((w) => `(?<![a-z0-9+#])${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:s|es)?(?![a-z0-9+#])`);
	return new RegExp(words.join('(?: \\S+){0,2} ')).test(joinCompounds(normalizeText(text)));
}
