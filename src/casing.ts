// ─── Type-level utilities ───

type CamelToSnake<S extends string> =
  S extends `${infer C}${infer Rest}`
    ? Rest extends Uncapitalize<Rest>
      ? `${Lowercase<C>}${CamelToSnake<Rest>}`
      : `${Lowercase<C>}_${CamelToSnake<Rest>}`
    : S;

type SnakeAliases<T> = {
  [K in keyof T as CamelToSnake<K & string> extends (K & string)
    ? never
    : CamelToSnake<K & string>]?: T[K];
};

export type FlexibleInput<T> = T & SnakeAliases<T>;

// ─── Runtime normalizer ───

const PASSTHROUGH_KEYS = new Set(['metadata', 'schema', 'logger']);

function snakeToCamel(key: string): string {
  return key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function normalizeValue(value: unknown): unknown {
  if (typeof value !== 'object' || value === null) return value;
  if (Array.isArray(value)) {
    return value.map((item) =>
      typeof item === 'object' && item !== null && !Array.isArray(item)
        ? normalizeObject(item as Record<string, unknown>)
        : item
    );
  }
  return normalizeObject(value as Record<string, unknown>);
}

function normalizeObject(obj: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.includes('_') ? snakeToCamel(key) : key;

    if (camelKey in result) continue;

    result[camelKey] = PASSTHROUGH_KEYS.has(camelKey) ? value : normalizeValue(value);
  }

  return result;
}

export function normalizeToCamel<T extends object>(obj: T): T {
  return normalizeObject(obj as Record<string, unknown>) as T;
}
