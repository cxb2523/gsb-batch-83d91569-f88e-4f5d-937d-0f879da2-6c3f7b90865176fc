// Tipos compartidos entre el servidor y la página para mostrar el avance de la búsqueda.

export type PlatformProgress = {
	id: string;
	name: string;
	state: 'pendiente' | 'buscando' | 'ok' | 'pausada' | 'error';
	term: string | null;
	done: number;
	total: number;
	found: number;
	created: number;
	/** Motivo del error o hasta cuándo está en pausa. */
	detail: string | null;
};

export type SearchProgress = {
	running: boolean;
	startedAt: string | null;
	finishedAt: string | null;
	platforms: PlatformProgress[];
};
