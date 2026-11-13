// SQLite's current_timestamp is UTC written without a zone ("2026-11-06 20:21:10"). Date.parse reads such
// text as local time, so it is read here as UTC. NaN for text that isn't a timestamp.
export function sqliteUtcMs(timestamp: string) {
  return Date.parse(`${timestamp.trim().replace(" ", "T")}Z`);
}
