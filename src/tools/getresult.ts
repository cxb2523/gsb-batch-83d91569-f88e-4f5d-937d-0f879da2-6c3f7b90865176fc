import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { ApiException } from 'capskip';
import { z } from 'zod';

import { mapError, toolError } from '../errors.js';
import { startProgress } from '../progress.js';
import { retrievedResultOutput, timeoutSchema } from '../schemas.js';
import { createClient } from '../solver.js';
import type { ToolContext } from '../solver.js';

const inputSchema = z.strictObject({
  captchaId: z
    .string()
    .min(1)
    .describe(
      'The CapSkip captcha id, copied from a solve tool that timed out (the error text '
      + 'names it, e.g. "CapSkip captcha id 48213") or from a solve result. Not a sitekey '
      + 'or a token.',
    ),
  timeout: timeoutSchema,
});

// The first poll fires this soon after the call starts, then the gap doubles up
// to the configured pollingInterval. The same curve the CapSkip SDK uses, so a
// retrieved solve polls no harder than the solve that submitted it did.
const INITIAL_POLL_SECONDS = 0.25;

type Polled =
  | {
    state: 'ready';
    code: string;
    userAgent?: string;
    respKey?: string;
    proxy?: string;
  }
  | { state: 'pending' }
  | { state: 'failed'; result: CallToolResult };

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, Math.max(seconds, 0) * 1000);
  });
}

/** An answer that is an object (Capy, AWS WAF) is stringified for the output schema. */
function codeOf(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value ?? '');
}

function readyFrom(data: Record<string, unknown>): Polled {
  const userAgent = typeof data.useragent === 'string'
    ? data.useragent
    : typeof data.userAgent === 'string'
      ? data.userAgent
      : undefined;

  return {
    state: 'ready',
    code: codeOf(data.request),
    ...(userAgent ? { userAgent } : {}),
    // Present even when empty for hCaptcha, which is how the server says "none".
    ...(Object.prototype.hasOwnProperty.call(data, 'respKey')
      && typeof data.respKey === 'string' ? { respKey: data.respKey } : {}),
    ...(typeof data.proxy === 'string' && data.proxy ? { proxy: data.proxy } : {}),
  };
}

/**
 * Read res.php once and classify the reply.
 *
 * This goes through `apiClient.res` rather than `getResult` on purpose: the SDK
 * turns "not ready" into the same NetworkException it uses for a real
 * connection failure, which would make a dropped connection indistinguishable
 * from a task still queued — the poll loop would keep retrying a server that is
 * gone. A raw res.php read only throws when something is genuinely wrong, so
 * any exception here is a reportable failure, not a retry.
 */
/** One place for the error context, so every failure names the same id. */
function failure(ctx: ToolContext, captchaId: string, err: unknown): Polled {
  return {
    state: 'failed',
    result: mapError(err, {
      host: ctx.config.host,
      port: ctx.config.port,
      captchaId,
    }),
  };
}

async function pollOnce(
  client: ReturnType<typeof createClient>,
  ctx: ToolContext,
  captchaId: string,
): Promise<Polled> {
  let raw: string;
  try {
    raw = await client.apiClient.res({
      key: ctx.config.apiKey,
      action: 'get',
      id: captchaId,
      json: 1,
    });
  } catch (err) {
    // Every throw here is a genuine failure — a lost connection, a non-200,
    // or an ERROR_* reply — never "not ready", which the body carries instead.
    return failure(ctx, captchaId, err);
  }

  const text = raw.trim();

  // CapSkip returns an empty body for an id it does not know and for one whose
  // answer was already read; both are indistinguishable from the brief empty
  // body right after a submit, so it is treated as "not ready" and bounded by
  // the caller's timeout rather than guessed at.
  if (text === '' || text === 'CAPCHA_NOT_READY') {
    return { state: 'pending' };
  }

  if (text.startsWith('OK|')) {
    return { state: 'ready', code: text.slice(3) };
  }

  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    return failure(ctx, captchaId, new ApiException(`cannot recognize response ${text}`));
  }

  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    return failure(ctx, captchaId, new ApiException(`cannot recognize response ${text}`));
  }

  const record = data as Record<string, unknown>;
  if (record.status === 0 && record.request === 'CAPCHA_NOT_READY') {
    return { state: 'pending' };
  }
  if (record.status === 1 && Object.prototype.hasOwnProperty.call(record, 'request')) {
    return readyFrom(record);
  }

  return failure(ctx, captchaId, new ApiException(`cannot recognize response ${text}`));
}

function formatResult(id: string, polled: Extract<Polled, { state: 'ready' }>, seconds: number) {
  const structured = {
    captchaId: id,
    code: polled.code,
    solveSeconds: Number(seconds.toFixed(2)),
    ...(polled.userAgent !== undefined ? { userAgent: polled.userAgent } : {}),
    ...(polled.respKey !== undefined ? { respKey: polled.respKey } : {}),
    ...(polled.proxy !== undefined ? { proxy: polled.proxy } : {}),
  };

  const uaLine = polled.userAgent !== undefined
    ? `\nSubmit it with this exact User-Agent, the one it was earned with: ${polled.userAgent}`
    : '';
  const extraLines =
    (polled.respKey !== undefined && polled.respKey !== ''
      ? `\nhCaptcha also handed the widget a respKey: ${polled.respKey}`
      : '')
    + (polled.proxy !== undefined
      ? `\nCapSkip earned this through its own DataDome proxy list: ${polled.proxy} — `
        + 'the cookie works only from that address.'
      : '');

  return {
    structured,
    text:
      `Retrieved the answer for CapSkip captcha id ${id} after ${structured.solveSeconds}s of polling.\n`
      + 'This is the token (or answer) the solve tool would have returned. Put it in '
      + "the response field for the captcha type you submitted — 'g-recaptcha-response' "
      + "for reCAPTCHA, 'cf-turnstile-response' for Turnstile, 'h-captcha-response' for "
      + "hCaptcha, 'mtcaptcha-verifiedtoken' for MTCaptcha, or the fields that type "
      + 'documents — and submit the form.\n'
      + `Token: ${structured.code}${uaLine}${extraLines}\n`
      + 'CapSkip serves each answer once; this one is gone from res.php now.',
  };
}

export function registerGetResultTool(server: McpServer, ctx: ToolContext): void {
  server.registerTool(
    'capskip_get_result',
    {
      title: 'Retrieve a pending or timed-out solve',
      description:
        'Fetch the answer for a captcha that was already submitted, by its CapSkip '
        + 'captcha id. Use this after a solve tool reports it did not finish in time: '
        + 'the task usually keeps running in CapSkip and its answer is still readable, '
        + 'whereas resubmitting a new challenge spends another solve and may use a '
        + 'sitekey that has already expired. Waits up to timeout (1-600s, default from '
        + 'CAPSKIP_RECAPTCHA_TIMEOUT) while CapSkip reports the task as not ready. '
        + 'Returns the same fields a solve tool does — captchaId, code, solveSeconds, '
        + 'plus userAgent/respKey/proxy when the answer carries one. An unknown id, or '
        + 'an answer already read, is reported as a readable error rather than a result.',
      inputSchema,
      outputSchema: retrievedResultOutput,
      // Reading the answer consumes it: res.php serves each result once, so this
      // is neither read-only nor idempotent. It destroys nothing either.
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    async (args, extra) => {
      const timeout = args.timeout ?? ctx.config.recaptchaTimeout;
      const captchaId = args.captchaId;
      const startedAt = Date.now();
      const client = createClient(ctx.config, timeout);

      const stop = startProgress({
        sendNotification: extra.sendNotification,
        progressToken: extra._meta?.progressToken,
        totalSeconds: timeout,
        label: `Waiting for captcha ${captchaId}`,
      });

      try {
        const deadline = startedAt + timeout * 1000;
        const ceiling = ctx.config.pollingInterval;
        let interval = Math.min(INITIAL_POLL_SECONDS, ceiling);

        while (Date.now() < deadline) {
          const polled = await pollOnce(client, ctx, captchaId);
          if (polled.state === 'failed') {
            return polled.result;
          }
          if (polled.state === 'ready') {
            const { structured, text } = formatResult(
              captchaId,
              polled,
              (Date.now() - startedAt) / 1000,
            );
            return {
              content: [{ type: 'text' as const, text }],
              structuredContent: structured,
            };
          }

          // Never sleep past the deadline: the wait must end when timeout says,
          // not up to one whole interval later.
          const remaining = (deadline - Date.now()) / 1000;
          await sleep(Math.min(interval, Math.max(remaining, 0)));
          interval = Math.min(interval * 2, ceiling);
        }

        return toolError(
          `CapSkip returned no answer for captcha id ${captchaId} within ${timeout}s. `
          + 'The task may still be queued — call capskip_get_result again with the same '
          + 'id to keep waiting. If it never resolves, the id may be wrong, or its '
          + 'answer may already have been read: CapSkip serves each result only once, '
          + 'and an empty res.php reply means either unknown or already read.',
        );
      } catch (err) {
        // A retrieval tool must not raise a protocol error either.
        return mapError(err, {
          host: ctx.config.host,
          port: ctx.config.port,
          captchaId,
          elapsedSeconds: (Date.now() - startedAt) / 1000,
        });
      } finally {
        stop();
      }
    },
  );
}
