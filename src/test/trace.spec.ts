import type { RedirectTraceEntry, RequestTrace, RetryTraceEntry } from '../node-wreq';
import assert from 'node:assert';
import { describe, test } from 'node:test';
import { fetch, RequestError } from '../node-wreq';
import { setupLocalTestServer } from './helpers/local-server';

function isRedirectEntry(entry: RequestTrace[number]): entry is RedirectTraceEntry {
  return entry.stage === 'redirect';
}

function isRetryEntry(entry: RequestTrace[number]): entry is RetryTraceEntry {
  return entry.stage === 'retry';
}

function assertSequential(trace: RequestTrace): void {
  trace.forEach((entry, index) => {
    assert.strictEqual(entry.sequence, index + 1, 'trace sequence must follow real order');
  });
}

describe('request trace', () => {
  const { getBaseUrl, retryAttempts } = setupLocalTestServer();

  test('does not allocate or expose a trace when trace is disabled', async () => {
    const response = await fetch(`${getBaseUrl()}/get`);

    assert.strictEqual(
      response.wreq.trace,
      undefined,
      'trace must stay undefined without trace:true'
    );

    const redirected = await fetch(`${getBaseUrl()}/redirect/start`);

    assert.strictEqual(
      redirected.wreq.trace,
      undefined,
      'redirects without trace:true must not expose a trace'
    );
  });

  test('records every redirect hop with the resolved Location target', async () => {
    const response = await fetch(`${getBaseUrl()}/redirect/chain?count=1`, {
      trace: true,
    });

    assert.strictEqual(response.status, 200);

    const trace = response.wreq.trace;

    assert.ok(trace, 'successful response should expose the trace');
    assert.strictEqual(trace.length, 2, 'chain with count=1 plus final hop yields two entries');
    assertSequential(trace);
    assert.ok(trace.every(isRedirectEntry), 'all entries should be redirect entries');

    const first = trace[0] as RedirectTraceEntry;

    assert.strictEqual(first.stage, 'redirect');
    assert.strictEqual(first.sequence, 1);
    assert.strictEqual(first.url, `${getBaseUrl()}/redirect/chain?count=1`);
    assert.strictEqual(first.method, 'GET');
    assert.strictEqual(first.status, 302);
    assert.strictEqual(first.location, '/redirect/chain?count=0');
    assert.strictEqual(first.toUrl, `${getBaseUrl()}/redirect/chain?count=0`);
    assert.ok(first.reason.includes('302'), 'reason should explain the redirect');

    const second = trace[1] as RedirectTraceEntry;

    assert.strictEqual(second.sequence, 2);
    assert.strictEqual(second.url, `${getBaseUrl()}/redirect/chain?count=0`);
    assert.strictEqual(second.location, '/redirect/final');
    assert.strictEqual(second.toUrl, `${getBaseUrl()}/redirect/final`);
  });

  test('keeps every followed hop and ends with the limit error when maxRedirects is exceeded', async () => {
    await assert.rejects(
      async () => {
        await fetch(`${getBaseUrl()}/redirect/chain?count=2`, {
          trace: true,
          maxRedirects: 1,
        });
      },
      (error: unknown) => {
        assert.ok(error instanceof RequestError);
        assert.strictEqual(error.code, 'ERR_TOO_MANY_REDIRECTS');

        const trace = error.wreq?.trace;

        assert.ok(trace, 'the limit error should carry the trace');
        assert.strictEqual(trace.length, 1, 'only the single followed hop should be recorded');
        assertSequential(trace);

        const entry = trace[0];

        assert.strictEqual(entry.stage, 'redirect');
        assert.strictEqual(entry.url, `${getBaseUrl()}/redirect/chain?count=2`);
        assert.strictEqual(entry.status, 302);
        assert.strictEqual(
          (entry as RedirectTraceEntry).toUrl,
          `${getBaseUrl()}/redirect/chain?count=1`
        );

        return true;
      }
    );
  });

  test('preserves the trace up to the point where a redirect loop is detected', async () => {
    await assert.rejects(
      async () => {
        await fetch(`${getBaseUrl()}/redirect/loop-a`, {
          trace: true,
        });
      },
      (error: unknown) => {
        assert.ok(error instanceof RequestError);
        assert.strictEqual(error.code, 'ERR_REDIRECT_LOOP');

        const trace = error.wreq?.trace;

        assert.ok(trace, 'the loop error should carry the trace');
        assert.strictEqual(
          trace.length,
          1,
          'only the completed loop-a -> loop-b hop exists; the loop is detected before following back to loop-a'
        );

        assertSequential(trace);

        const [first] = trace as RedirectTraceEntry[];

        assert.strictEqual(first.stage, 'redirect');
        assert.strictEqual(first.url, `${getBaseUrl()}/redirect/loop-a`);
        assert.strictEqual(first.toUrl, `${getBaseUrl()}/redirect/loop-b`);
        assert.strictEqual(first.location, '/redirect/loop-b');

        return true;
      }
    );
  });

  test('only contains already completed hops when manual mode stops a redirect', async () => {
    const response = await fetch(`${getBaseUrl()}/redirect/start`, {
      trace: true,
      redirect: 'manual',
    });

    assert.strictEqual(response.status, 302);

    const trace = response.wreq.trace;

    assert.ok(trace, 'manual response should still expose a trace');
    assert.deepStrictEqual(trace, [], 'no hop has been followed yet, so no entry exists');
  });

  test('stays empty when redirect error mode throws on the first redirect', async () => {
    await assert.rejects(
      async () => {
        await fetch(`${getBaseUrl()}/redirect/start`, {
          trace: true,
          redirect: 'error',
        });
      },
      (error: unknown) => {
        assert.ok(error instanceof RequestError);
        assert.strictEqual(error.code, 'ERR_REDIRECT');

        const trace = error.wreq?.trace;

        assert.ok(trace, 'the redirect error should carry the trace object');
        assert.deepStrictEqual(
          trace,
          [],
          'nothing was followed before the error, so no entries may be fabricated'
        );

        return true;
      }
    );
  });

  test('records each retry attempt with its attempt number and triggering status', async () => {
    retryAttempts.set('trace-retry-ok', 0);

    const response = await fetch(`${getBaseUrl()}/retry?key=trace-retry-ok&failCount=2`, {
      trace: true,
      retry: {
        limit: 2,
        statusCodes: [503],
        backoff: () => 0,
      },
    });

    assert.strictEqual(response.status, 200);

    const trace = response.wreq.trace;

    assert.ok(trace);
    assert.strictEqual(trace.length, 2, 'the two failed attempts should be recorded');
    assertSequential(trace);
    assert.ok(trace.every(isRetryEntry));

    const [first, second] = trace as RetryTraceEntry[];

    assert.strictEqual(first.attempt, 1);
    assert.strictEqual(first.url, `${getBaseUrl()}/retry?key=trace-retry-ok&failCount=2`);
    assert.strictEqual(first.method, 'GET');
    assert.strictEqual(first.status, 503);
    assert.strictEqual(first.errorName, undefined);
    assert.ok(first.reason.includes('503'));
    assert.ok(first.reason.includes('attempt 1'));

    assert.strictEqual(second.attempt, 2);
    assert.strictEqual(second.status, 503);
    assert.ok(second.reason.includes('attempt 2'));

    const body = await response.json<{ attempt: number }>();

    assert.strictEqual(body.attempt, 3);
  });

  test('includes the final failed attempt after retries are exhausted', async () => {
    retryAttempts.set('trace-retry-exhausted', 0);

    await assert.rejects(
      async () => {
        await fetch(`${getBaseUrl()}/retry?key=trace-retry-exhausted&failCount=2`, {
          trace: true,
          throwHttpErrors: true,
          retry: {
            limit: 1,
            statusCodes: [503],
            backoff: () => 0,
          },
        });
      },
      (error: unknown) => {
        assert.ok(error instanceof RequestError);

        const trace = error.wreq?.trace;

        assert.ok(trace, 'exhausted error should carry the trace');
        assert.strictEqual(trace.length, 2);
        assertSequential(trace);

        const [trigger, terminal] = trace as RetryTraceEntry[];

        assert.strictEqual(trigger.stage, 'retry');
        assert.strictEqual(trigger.attempt, 1);
        assert.strictEqual(trigger.status, 503);
        assert.ok(trigger.reason.includes('Retry triggered'), trigger.reason);

        assert.strictEqual(terminal.stage, 'retry');
        assert.strictEqual(terminal.attempt, 2, 'the last failed attempt must be present');
        assert.strictEqual(terminal.status, 503);
        assert.ok(terminal.reason.includes('Retry attempts exhausted'), terminal.reason);

        return true;
      }
    );
  });

  test('records error name and error code for timeout-driven retries', async () => {
    retryAttempts.set('trace-timeout-ok', 0);

    const response = await fetch(
      `${getBaseUrl()}/retry/timeout?key=trace-timeout-ok&failCount=1&delayMs=750`,
      {
        trace: true,
        timeout: 250,
        retry: {
          limit: 1,
          errorCodes: ['ERR_TIMEOUT'],
          backoff: () => 0,
        },
      }
    );

    assert.strictEqual(response.status, 200);

    const trace = response.wreq.trace;

    assert.ok(trace);
    assert.strictEqual(trace.length, 1);

    const entry = trace[0] as RetryTraceEntry;

    assert.strictEqual(entry.stage, 'retry');
    assert.strictEqual(entry.attempt, 1);
    assert.strictEqual(entry.status, undefined, 'no response status exists for a timeout');
    assert.strictEqual(entry.errorName, 'TimeoutError');
    assert.strictEqual(entry.errorCode, 'ERR_TIMEOUT');
    assert.ok(entry.reason.includes('TimeoutError'));
    assert.ok(entry.reason.includes('ERR_TIMEOUT'));
  });

  test('records the terminal timeout attempt when error retries are exhausted', async () => {
    retryAttempts.set('trace-timeout-exhausted', 0);

    await assert.rejects(
      async () => {
        await fetch(
          `${getBaseUrl()}/retry/timeout?key=trace-timeout-exhausted&failCount=3&delayMs=750`,
          {
            trace: true,
            timeout: 250,
            retry: {
              limit: 1,
              errorCodes: ['ERR_TIMEOUT'],
              backoff: () => 0,
            },
          }
        );
      },
      (error: unknown) => {
        assert.ok(error instanceof RequestError);
        assert.strictEqual(error.code, 'ERR_TIMEOUT');

        const trace = error.wreq?.trace;

        assert.ok(trace);
        assert.strictEqual(trace.length, 2);
        assertSequential(trace);

        const [trigger, terminal] = trace as RetryTraceEntry[];

        assert.strictEqual(trigger.attempt, 1);
        assert.strictEqual(trigger.errorName, 'TimeoutError');
        assert.ok(trigger.reason.includes('Retry triggered'));

        assert.strictEqual(terminal.attempt, 2);
        assert.strictEqual(terminal.errorName, 'TimeoutError');
        assert.strictEqual(terminal.errorCode, 'ERR_TIMEOUT');
        assert.ok(terminal.reason.includes('Retry attempts exhausted'), terminal.reason);

        return true;
      }
    );
  });

  test('records redirects and retries in the order they actually happen', async () => {
    retryAttempts.set('trace-mixed', 0);

    const target = encodeURIComponent('/retry?key=trace-mixed&failCount=1');
    const response = await fetch(`${getBaseUrl()}/redirect/start?target=${target}`, {
      trace: true,
      retry: {
        limit: 1,
        statusCodes: [503],
        backoff: () => 0,
      },
    });

    assert.strictEqual(response.status, 200);

    const trace = response.wreq.trace;

    assert.ok(trace);
    assert.strictEqual(trace.length, 2);
    assertSequential(trace);

    const redirect = trace[0] as RedirectTraceEntry;
    const retry = trace[1] as RetryTraceEntry;

    assert.strictEqual(redirect.stage, 'redirect');
    assert.strictEqual(redirect.url, `${getBaseUrl()}/redirect/start?target=${target}`);
    assert.strictEqual(redirect.toUrl, `${getBaseUrl()}/retry?key=trace-mixed&failCount=1`);

    assert.strictEqual(retry.stage, 'retry');
    assert.strictEqual(retry.attempt, 1);
    assert.strictEqual(retry.url, `${getBaseUrl()}/retry?key=trace-mixed&failCount=1`);
    assert.strictEqual(retry.status, 503);
  });

  test('exposes an empty trace for a simple successful request with trace enabled', async () => {
    const response = await fetch(`${getBaseUrl()}/get`, {
      trace: true,
    });

    assert.strictEqual(response.status, 200);
    assert.ok(response.wreq.trace);
    assert.deepStrictEqual(response.wreq.trace, []);
  });
});
