import { importKeywordSeed } from '$lib/server/features/keywords/commands/import-keyword-seed';
import type { ServerInit } from '@sveltejs/kit';

// Al arrancar: agrega las palabras clave nuevas de profile/keywords.json.
export const init: ServerInit = () => {
	importKeywordSeed();
};
