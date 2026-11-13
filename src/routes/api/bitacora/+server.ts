import { json } from '@sveltejs/kit';
import { listPageLogs } from '$lib/server/features/search/page-log';

// Bitácora página por página de Computrabajo, para mostrar el detalle de qué se pidió,
// cómo terminó cada página y desde dónde se reanuda la próxima búsqueda.
export function GET({ url }) {
	const platform = url.searchParams.get('plataforma') ?? 'computrabajo';
	const limit = Math.min(Number(url.searchParams.get('limite')) || 200, 1000);
	return json(listPageLogs(platform, limit));
}
