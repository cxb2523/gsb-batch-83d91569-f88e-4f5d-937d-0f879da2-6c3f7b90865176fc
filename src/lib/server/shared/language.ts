import { normalizeText } from './normalize';

// Palabras muy frecuentes que casi no aparecen en el otro idioma. Los nombres de tecnologías
// (en inglés en casi todas las vacantes) no cuentan.
const WORDS: Record<string, Set<string>> = {
	es: new Set(['de', 'la', 'el', 'y', 'en', 'los', 'las', 'para', 'con', 'que', 'una', 'por', 'del', 'experiencia', 'conocimientos', 'buscamos', 'años', 'trabajo', 'equipo', 'nuestro', 'requisitos']),
	en: new Set(['the', 'and', 'with', 'you', 'we', 'our', 'for', 'to', 'of', 'are', 'will', 'your', 'experience', 'team', 'years', 'requirements', 'skills', 'work', 'looking'])
};
const MIN_HITS = 8;

/** Idioma de una descripción: 'es', 'en' o null si es muy corta o no se distingue. */
export function detectLanguage(text: string): 'es' | 'en' | null {
	const counts = { es: 0, en: 0 };
	for (const word of normalizeText(text).split(' ')) {
		if (WORDS.es.has(word)) counts.es++;
		if (WORDS.en.has(word)) counts.en++;
	}
	if (counts.es + counts.en < MIN_HITS) return null;
	if (counts.es >= counts.en * 2) return 'es';
	if (counts.en >= counts.es * 2) return 'en';
	return null; // mezcla: no se descarta
}
