'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { startHarness } = require('../test-helpers/harness.js');
const { CODE } = require('../test-helpers/mockServer.js');

// The retrieval tool is the answer to "the solve timed out, do not resubmit".
// Its failure modes matter as much as its success path: an id that does not
// exist, an answer already consumed, and a CapSkip that goes away mid-wait must
// all come back as readable errors, never protocol throwables.

test('a timed-out solve can be retrieved by its captcha id once released', async () => {
  const { client, close, mock } = await startHarness();
  try {
    // "hold" keeps the task queued, so the solve below is guaranteed to hit its
    // 1-second deadline with a real captcha id already assigned.
    const solve = await client.callTool({
      name: 'capskip_solve_recaptcha',
      arguments: { sitekey: '6LtestKey', url: 'https://hold.example.com/login', timeout: 1 },
    });
    assert.strictEqual(solve.isError, true, 'the solve is expected to time out');
    const idMatch = /captcha id (\w+)/i.exec(solve.content[0].text);
    assert.ok(idMatch, `the timeout text must name the id: ${solve.content[0].text}`);
    const captchaId = idMatch[1];

    // The timeout text is the only pointer the model gets: it has to name the
    // retrieval tool and carry the id, or the answer is effectively lost.
    assert.match(solve.content[0].text, /capskip_get_result/);
    assert.match(solve.content[0].text, new RegExp(`capskip_get_result.*${captchaId}`));

    assert.strictEqual(mock.server.wasServed(captchaId), false);

    // Release the held task while the retrieval tool is already waiting, so
    // this exercises the polling loop rather than a single lucky poll. The
    // release lands past the 2s progress tick: the notification is what keeps a
    // client from timing the call out during a long wait.
    setTimeout(() => mock.server.release(captchaId), 2600);

    const notifications = [];
    const retrieved = await client.callTool(
      {
        name: 'capskip_get_result',
        arguments: { captchaId, timeout: 5 },
      },
      undefined,
      { onprogress: (p) => { notifications.push(p); } },
    );

    assert.notStrictEqual(retrieved.isError, true, retrieved.content?.[0]?.text);
    assert.strictEqual(retrieved.structuredContent.captchaId, captchaId);
    assert.strictEqual(retrieved.structuredContent.code, CODE);
    assert.ok(
      typeof retrieved.structuredContent.solveSeconds === 'number',
      'solveSeconds must be reported',
    );
    assert.match(retrieved.content[0].text, /Token:/);

    // The long wait must keep the client's tool-call timeout open, exactly as a
    // solve does.
    assert.ok(notifications.length >= 1, 'retrieval should emit progress notifications');
    for (const n of notifications) {
      assert.strictEqual(n.total, 5);
      assert.match(n.message, /Waiting for captcha/);
    }
  } finally {
    await close();
  }
});

test('an id CapSkip does not recognise is a readable error, not a throw', async () => {
  const { client, close } = await startHarness();
  try {
    const result = await client.callTool({
      name: 'capskip_get_result',
      arguments: { captchaId: 'badid', timeout: 2 },
    });
    assert.strictEqual(result.isError, true);
    assert.match(result.content[0].text, /does not know captcha id/i);
    assert.match(result.content[0].text, /already read/i);
  } finally {
    await close();
  }
});

test('an answer already read once is reported as a readable error', async () => {
  const { client, close, mock } = await startHarness();
  try {
    // Solve normally: the mock serves the answer, and (like real CapSkip) will
    // answer every later read of that id with an empty body.
    const solved = await client.callTool({
      name: 'capskip_solve_recaptcha',
      arguments: { sitekey: '6LtestKey', url: 'https://example.com/login' },
    });
    assert.notStrictEqual(solved.isError, true, solved.content?.[0]?.text);
    const captchaId = solved.structuredContent.captchaId;
    assert.ok(mock.server.wasServed(captchaId));

    const again = await client.callTool({
      name: 'capskip_get_result',
      arguments: { captchaId, timeout: 1 },
    });
    assert.strictEqual(again.isError, true);
    assert.match(again.content[0].text, new RegExp(`no answer for captcha id ${captchaId}`));
    assert.match(again.content[0].text, /already/);
  } finally {
    await close();
  }
});

test('a connection lost mid-poll is reported, not retried forever', async () => {
  const { client, close, mock } = await startHarness({ pollingInterval: 1 });
  let mockCloseError = null;
  try {
    const pending = client.callTool({
      name: 'capskip_get_result',
      arguments: { captchaId: 'hold1', timeout: 6 },
    });

    // Take CapSkip away after the first poll, so the loss lands during the
    // wait. The first poll is immediate; the next is a quarter-second later.
    setTimeout(() => {
      mock.server.close((err) => { mockCloseError = err ?? null; });
    }, 300);

    const result = await pending;
    assert.strictEqual(result.isError, true, 'a lost connection must fail the call');
    assert.match(result.content[0].text, /not reachable/i);
    assert.match(result.content[0].text, /CAPSKIP_HOST/);
  } finally {
    await close();
  }
  // Closing a server that is already closed reports ERR_SERVER_NOT_RUNNING
  // through the callback; that is expected here and not a test failure.
  assert.ok(
    mockCloseError === null || mockCloseError.code === 'ERR_SERVER_NOT_RUNNING',
    `unexpected close error: ${mockCloseError}`,
  );
});

test('timeout is validated to the same 1-600s bounds as the solve tools', async () => {
  const { client, close } = await startHarness();
  try {
    for (const timeout of [0, 601, 12.5]) {
      const result = await client.callTool({
        name: 'capskip_get_result',
        arguments: { captchaId: 'badid', timeout },
      });
      assert.strictEqual(result.isError, true, `timeout ${timeout} should be rejected`);
      assert.match(result.content[0].text, /timeout/);
    }
  } finally {
    await close();
  }
});

test('captchaId is required', async () => {
  const { client, close } = await startHarness();
  try {
    const result = await client.callTool({
      name: 'capskip_get_result',
      arguments: {},
    });
    assert.strictEqual(result.isError, true);
    assert.match(result.content[0].text, /captchaId/);
  } finally {
    await close();
  }
});

test('an empty res.php body is treated as not ready, then succeeds', async () => {
  // Right after submit, CapSkip answers an empty 200 body before it starts
  // reporting CAPCHA_NOT_READY. The retrieval tool must not read that as an
  // unknown id on the first poll.
  const { client, close } = await startHarness();
  try {
    const result = await client.callTool({
      name: 'capskip_get_result',
      arguments: { captchaId: 'empty1', timeout: 5 },
    });
    assert.notStrictEqual(result.isError, true, result.content?.[0]?.text);
    assert.strictEqual(result.structuredContent.code, CODE);
  } finally {
    await close();
  }
});

test('a whole wait that never resolves ends with guidance to retry, not silence', async () => {
  const { client, close } = await startHarness();
  try {
    const result = await client.callTool({
      name: 'capskip_get_result',
      arguments: { captchaId: 'never1', timeout: 1 },
    });
    assert.strictEqual(result.isError, true);
    assert.match(result.content[0].text, /still be queued/i);
    assert.match(result.content[0].text, /call capskip_get_result again/i);
  } finally {
    await close();
  }
});
