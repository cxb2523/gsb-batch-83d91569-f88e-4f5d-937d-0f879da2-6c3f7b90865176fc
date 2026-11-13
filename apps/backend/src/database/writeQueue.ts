import type { TrackerDatabase } from "./db";

let tail: Promise<unknown> = Promise.resolve();

export function enqueueWrite<T>(job: () => T | Promise<T>): Promise<T> {
  const run = tail.then(job, job);
  tail = run.catch(() => undefined);
  return run;
}

export function resetWriteQueueForTests() {
  tail = Promise.resolve();
}

// The write policy for actions: queued behind other writes and atomic. A thrown error rolls back everything.
export function runWrite<T>(db: TrackerDatabase, job: () => T): Promise<T> {
  return enqueueWrite(() => db.transaction(job)());
}
