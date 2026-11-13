import { normalizeText } from './normalize';

const DAY = 86_400_000;
const UNITS: Record<string, number> = {
	minuto: 60_000,
	hora: 3_600_000,
	dia: DAY,
	semana: 7 * DAY,
	mes: 30 * DAY
};
const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

export type PublishedDate = {
	date: Date;
	/**
	 * La fecha es solo un tope ("Más de 30 días"): no dice cuándo se publicó, así que no sirve
	 * para detectar republicaciones.
	 */
	approximate: boolean;
};

const atNoon = (ms: number) => {
	const date = new Date(ms);
	date.setUTCHours(12, 0, 0, 0);
	return date;
};

/**
 * Fechas como las muestran los portales: "Hace 3 horas", "Ayer", "Hace 5 días",
 * "14 de septiembre", "Más de 30 días". Se redondean al día (12:00 UTC) para que la misma
 * vacante vista en búsquedas distintas tenga la misma fecha. Devuelve null si no la entiende.
 */
export function parsePublishedDate(text: string, now = new Date()): PublishedDate | null {
	const t = normalizeText(text);

	if (/\b(hoy|ahora|recien)\b/.test(t)) return { date: atNoon(now.getTime()), approximate: false };
	if (/\bayer\b/.test(t)) return { date: atNoon(now.getTime() - DAY), approximate: false };

	const relative = t.match(/(hace\s+)?(mas de\s+)?(\d+|un|una)\s+(minuto|hora|dia|semana|mes)/);
	if (relative && (relative[1] || relative[2])) {
		const amount = /^\d+$/.test(relative[3]) ? Number(relative[3]) : 1;
		return {
			date: atNoon(now.getTime() - amount * UNITS[relative[4]]),
			approximate: !!relative[2]
		};
	}

	// "14 de septiembre" o "14 de septiembre de 2025"; sin año, el último que ya pasó
	const absolute = t.match(/(\d{1,2}) de ([a-z]+)(?: de (\d{4}))?/);
	const month = absolute ? MONTHS.indexOf(absolute[2]) : -1;
	if (absolute && month >= 0) {
		const year = absolute[3] ? Number(absolute[3]) : now.getUTCFullYear();
		let date = new Date(Date.UTC(year, month, Number(absolute[1]), 12));
		if (!absolute[3] && date > now) date = new Date(Date.UTC(year - 1, month, Number(absolute[1]), 12));
		return { date, approximate: false };
	}

	return null;
}
