export function selectMiniSource(capabilities, requested) {
  if (!capabilities || capabilities.apiVersion !== 1 || !Array.isArray(capabilities.sources)
    || !capabilities.sources.includes(capabilities.defaultSource)) throw new Error("Invalid dashboard capabilities");
  return capabilities.sources.includes(requested) ? requested : capabilities.defaultSource;
}

// Keep the last snapshot on failure, never mistake it for a fresh response.
export function createMiniData({ fetchJson, onChange, now = Date.now }) {
  let source = null;
  let snapshot = { data: null, error: false, receivedAt: null, source: null };
  let pending = null;
  return {
    get snapshot() { return snapshot; },
    clear() {
      snapshot = { data: null, error: false, receivedAt: null, source };
      onChange(snapshot);
    },
    setSource(value) {
      if (source === value) return;
      source = value;
      snapshot = { data: null, error: false, receivedAt: null, source };
      onChange(snapshot);
    },
    async load() {
      if (pending) return pending;
      if (!source) return;
      const requested = source;
      pending = (async () => {
        try {
          const data = await fetchJson(`./api/usage?source=${encodeURIComponent(requested)}`);
          if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid usage response");
          if (requested === source) snapshot = { data, error: false, receivedAt: now(), source };
        } catch {
          if (requested === source) snapshot = { ...snapshot, error: true };
        }
        if (requested === source) onChange(snapshot);
      })().finally(() => { pending = null; });
      return pending;
    },
  };
}
