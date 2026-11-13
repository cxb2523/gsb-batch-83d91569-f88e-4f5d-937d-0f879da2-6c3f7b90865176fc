// Serialize provider calls, including retries and body downloads. All callers share a cooldown.
export function requestPacer({ intervalMs = 1000, now = Date.now, pause = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  let tail = Promise.resolve(), next = 0, cooldown = 0;
  return {
    defer(ms) { cooldown = Math.max(cooldown, now() + ms); },
    run(job) {
      const result = tail.then(async () => {
        while (Math.max(next, cooldown) > now()) await pause(Math.max(next, cooldown) - now());
        next = now() + intervalMs;
        return job();
      });
      tail = result.catch(() => {}); return result;
    }
  };
}
