/** Un motivo de lista negra y las vacantes que lo prueban. Se guarda como JSON en companies.list_reason. */
export type Reason = { kind: 'repetida' | 'descarte' | 'manual'; text: string; ids: number[] };

export function parseReasons(raw: string | null): Reason[] {
	if (!raw) return [];
	try {
		return JSON.parse(raw);
	} catch {
		return [{ kind: 'repetida', text: raw, ids: [] }]; // motivo guardado antes de usar JSON
	}
}
