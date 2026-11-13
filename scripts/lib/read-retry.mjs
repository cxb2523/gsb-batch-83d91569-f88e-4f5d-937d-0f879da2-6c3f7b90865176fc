export async function readWithRetry(job, { pause = ms => new Promise(resolve => setTimeout(resolve, ms)), onLimit = () => {}, random = Math.random, maxWaitMs = 300000 } = {}) {
  for (let attempt = 0; ; attempt++) {
    try { return await job(); }
    catch (error) {
      if (error.code === 'rate_limited') {
        const delay = Math.max(error.retryAfterMs || 60000 * 2 ** attempt, 1000) + Math.floor(random() * 1000);
        if (attempt >= 3 || delay > maxWaitMs) throw error;
        await onLimit(delay); await pause(delay); continue;
      }
      const transient = ['upstream_error', 'session_expired'].includes(error.code) || ['TimeoutError', 'AbortError'].includes(error.name);
      if (!transient || attempt >= 2) throw error;
      await pause(1000 * (attempt + 1));
    }
  }
}
