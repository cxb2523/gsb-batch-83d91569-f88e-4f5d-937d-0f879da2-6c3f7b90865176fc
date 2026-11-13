// Batch profile collection.
//
// Input: handles without the leading '@'. Output: one record per handle, in the
// exact input order, each carrying its own status so a private account, a
// missing account, a retry-exhausted call and a success never blur together.
//
// The free tier allows five concurrent requests and answers overflow with 429
// concurrency_limit instead of queueing. A counting semaphore keeps the batch
// under that ceiling, and a concurrency-limit response is backed off and
// retried before the handle is recorded as failed. One handle failing never
// interrupts the others.

import {
    ConcurrencyLimitError,
    InstagramApiError,
    ProfileNotFoundError,
    createProfileClient,
} from './instagram-client.mjs';

export const BATCH_STATUS = Object.freeze({
    SUCCESS: 'success',
    PRIVATE: 'private',
    NOT_FOUND: 'not_found',
    ERROR: 'error',
});

// The README documents five concurrent requests on the free plan. Callers on a
// bigger plan can pass a higher value.
const DEFAULT_CONCURRENCY = 5;
const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_INITIAL_DELAY_MS = 1000;

function normalizeHandle(value) {
    if (typeof value !== 'string') return '';
    return value.trim().replace(/^@+/, '');
}

function concurrencyFromEnv() {
    const parsed = Number(process.env.HASDATA_MAX_CONCURRENCY);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : DEFAULT_CONCURRENCY;
}

// Keep only the fields the batch contract names. Optional fields are copied
// only when present, because the upstream omits fields rather than nulling them
// and the output should mirror that rather than inventing undefined keys.
function buildData(profile) {
    const data = {
        id: profile.id,
        username: profile.username,
        followersCount: profile.followersCount,
        followsCount: profile.followsCount,
    };
    if ('fullName' in profile) data.fullName = profile.fullName;
    if ('verified' in profile) data.verified = profile.verified;
    if ('bioLinks' in profile) data.bioLinks = profile.bioLinks;
    // Only the number is retained; the posts themselves are not copied.
    if (Array.isArray(profile.latestPosts)) data.latestPostsCount = profile.latestPosts.length;
    return data;
}

// A minimal counting semaphore. Worker slots are awaited in handle order, but
// the loop never waits for a slow handle before starting the next free slot,
// and results are placed back by index so output order matches input order.
function createSemaphore(size) {
    let available = size;
    const queue = [];

    async function acquire() {
        if (available > 0) {
            available -= 1;
            return;
        }
        await new Promise((resolve) => queue.push(resolve));
        // The releasing worker hands this slot straight over; no decrement.
    }

    function release() {
        const next = queue.shift();
        if (next) next();
        else available += 1;
    }

    return { acquire, release };
}

// One handle, with its own retry budget. Concurrency-limit responses are the
// only retried branch; every other error is classified and returned at once.
async function collectOne(handle, client, options, semaphore) {
    const { maxAttempts, initialDelayMs, sleep } = options;
    await semaphore.acquire();
    try {
        let lastError;
        for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
            try {
                const profile = await client.getProfile(handle);
                // A private account answers with private: true and little else.
                // Missing biography / latestPosts are expected there, not errors.
                return {
                    handle,
                    status: profile.private === true ? BATCH_STATUS.PRIVATE : BATCH_STATUS.SUCCESS,
                    data: buildData(profile),
                };
            } catch (err) {
                lastError = err;
                if (!(err instanceof ConcurrencyLimitError) || attempt === maxAttempts) break;
                // Exponential backoff: 1s, 2s, 4s, ... with a little jitter so
                // colliding batches do not retry in lockstep.
                const backoff = initialDelayMs * 2 ** (attempt - 1);
                const jitter = Math.floor(backoff / 4);
                await sleep(backoff + (jitter ? jitter % (attempt + 1) : 0));
            }
        }

        if (lastError instanceof ProfileNotFoundError) {
            return { handle, status: BATCH_STATUS.NOT_FOUND, error: lastError.message };
        }
        const reason =
            lastError instanceof ConcurrencyLimitError
                ? `concurrency_limit persisted after ${maxAttempts} attempts: ${lastError.message}`
                : lastError instanceof InstagramApiError
                  ? lastError.message
                  : `unexpected error: ${lastError?.message ?? String(lastError)}`;
        return { handle, status: BATCH_STATUS.ERROR, error: reason };
    } finally {
        semaphore.release();
    }
}

// Handles are processed concurrently under the semaphore; the returned array is
// in input order. A per-handle failure is contained inside that handle's record.
export async function collectProfiles(handles, options = {}) {
    const list = Array.isArray(handles) ? handles : [];
    const client = options.client ?? createProfileClient(options);
    const concurrency = options.concurrency ?? concurrencyFromEnv();
    if (!Number.isInteger(concurrency) || concurrency < 1) {
        throw new Error('concurrency must be a positive integer');
    }
    const settings = {
        maxAttempts: options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS,
        initialDelayMs: options.initialDelayMs ?? DEFAULT_INITIAL_DELAY_MS,
        sleep: options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms))),
    };
    const semaphore = createSemaphore(concurrency);

    const invalid = (handle) => ({
        handle: typeof handle === 'string' ? handle.trim() : String(handle ?? ''),
        status: BATCH_STATUS.ERROR,
        error: 'invalid handle: expected a non-empty username without @',
    });

    const workers = list.map((rawHandle) => {
        const handle = normalizeHandle(rawHandle);
        if (!handle) return Promise.resolve(invalid(rawHandle));
        return collectOne(handle, client, settings, semaphore);
    });
    return Promise.all(workers);
}
