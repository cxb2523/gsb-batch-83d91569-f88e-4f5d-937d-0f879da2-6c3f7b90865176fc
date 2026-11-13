// Escalera de pausas por bloqueo. Sin base de datos, para poder probarla sola.

// por defecto: 1 día, 2, 4 y después una semana
export const DEFAULT_PAUSE_MINUTES = [1_440, 2_880, 5_760, 10_080];

/** Minutos de pausa para el bloqueo número `failures` (1 = el primero); el último escalón se repite. */
export function pauseMinutesFor(failures: number, ladderMinutes = DEFAULT_PAUSE_MINUTES): number {
	return ladderMinutes[Math.min(Math.max(failures, 1), ladderMinutes.length) - 1];
}
