import http, { Server } from 'http';
import { Socket } from 'net';
import { CapMonsterCloudClientFactory } from './CapMonsterCloudClientFactory';
import { CaptchaResult } from './CaptchaResult';
import { ClientOptions } from './ClientOptions';
import { ErrorType } from './ErrorType';
import { RecaptchaV2Request } from './Requests/RecaptchaV2Request';
// The new error identifier has to be reachable through the public package entry point.
import { ErrorType as PublicErrorType } from './index';

const createClient = (port: number) =>
  CapMonsterCloudClientFactory.Create(
    new ClientOptions({ clientKey: '<your capmonster.cloud API key>', serviceUrl: `http://localhost:${port}` }),
  );

const createRecaptchaV2Request = () =>
  new RecaptchaV2Request({
    websiteURL: 'https://example.com',
    websiteKey: 'websiteKey',
  });

type MockOptions = {
  // 'processing' answers every getTaskResult with status processing; 'ready' answers with a solution.
  pollStatus?: 'processing' | 'ready';
  // When true, each getTaskResult response is held until releaseNextPoll() is called.
  holdPoll?: boolean;
};

type ControllableMock = {
  port: number;
  requests: string[];
  // Resolves once exactly `count` requests have reached the server.
  waitForRequestCount: (count: number) => Promise<void>;
  releaseNextPoll: () => void;
  destroy: () => Promise<void>;
};

const processingBody = '{"errorId":0,"status":"processing"}';
const readyBody = '{"errorId":0,"status":"ready","solution":{"gRecaptchaResponse":"answer"}}';

/**
 * Local mock of the CapMonster Cloud API that records every request body and lets the test
 * control getTaskResult responses, so abort/result interleaving can be driven deterministically
 * without wall-clock timers. No real API or key is ever contacted.
 */
function createControllableMock(options: MockOptions = {}): Promise<ControllableMock> {
  const { pollStatus = 'processing', holdPoll = false } = options;
  return new Promise((resolve, reject) => {
    const requests: string[] = [];
    const waiters: Array<{ count: number; resolve: () => void }> = [];
    const sockets = new Set<Socket>();
    let releaseHeldPoll: (() => void) | undefined;

    const notifyWaiters = (): void => {
      for (let i = waiters.length - 1; i >= 0; i--) {
        if (requests.length >= waiters[i].count) {
          const [w] = waiters.splice(i, 1);
          w.resolve();
        }
      }
    };

    const server: Server = http.createServer((req, res) => {
      const chunks: Array<Uint8Array> = [];
      req.on('data', (chunk) => chunks.push(chunk));
      req.on('end', () => {
        requests.push(Buffer.concat(chunks).toString('utf8'));
        notifyWaiters();

        if (req.url === '/createTask') {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end('{"errorId":0,"taskId":1234567}');
          return;
        }

        const send = (): void => {
          if (!res.writableEnded) {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(pollStatus === 'ready' ? readyBody : processingBody);
          }
        };

        if (holdPoll) {
          // Keep the response (and therefore the in-flight request) until the test releases it.
          releaseHeldPoll = send;
        } else {
          send();
        }
      });
      // An aborted client destroys the socket; nothing to do, the response simply never lands.
      req.on('error', () => undefined);
    });

    server.on('error', reject);
    server.on('connection', (socket: Socket) => {
      // Track sockets so keep-alive connections can be closed deterministically on teardown.
      sockets.add(socket);
      socket.on('close', () => sockets.delete(socket));
    });
    server.listen(0, () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        return reject(new Error('Could not get server address'));
      }
      resolve({
        port: address.port,
        requests,
        waitForRequestCount: (count: number) =>
          new Promise<void>((r) => {
            if (requests.length >= count) {
              r();
            } else {
              waiters.push({ count, resolve: r });
            }
          }),
        releaseNextPoll: () => releaseHeldPoll && releaseHeldPoll(),
        destroy: () =>
          new Promise((r) => {
            sockets.forEach((socket) => socket.destroy());
            server.close(() => r());
          }),
      });
    });
  });
}

const fastTimeouts = { firstRequestDelay: 0, firstRequestNoCacheDelay: 0, requestsInterval: 1000 * 10, timeout: 1000 * 180 };

describe('Check Solve() cancellation outcomes', () => {
  it('exposes the Cancelled error type from the public exports', () => {
    expect(PublicErrorType.Cancelled).toBe('Cancelled');
    expect(PublicErrorType.Cancelled).toBe(ErrorType.Cancelled);
    expect(PublicErrorType.Cancelled).not.toBe(PublicErrorType.Timeout);
  });

  it('should return Cancelled and stop polling when the caller aborts between requests', async () => {
    expect.assertions(6);

    const srv = await createControllableMock({ pollStatus: 'processing' });

    try {
      const cmcClient = createClient(srv.port);
      const abortController = new AbortController();

      const solvePromise = cmcClient.Solve(createRecaptchaV2Request(), fastTimeouts, abortController);

      // Wait until the first getTaskResult (request #2) has actually been sent and answered,
      // so the abort happens while Solve is sleeping before the next poll.
      await srv.waitForRequestCount(2);
      abortController.abort();

      const task = await solvePromise;

      expect(task).toBeInstanceOf(CaptchaResult);
      expect(task.solution).toBeUndefined();
      expect(task).toHaveProperty('error', ErrorType.Cancelled);
      // createTask + exactly one getTaskResult reached the mock before the abort.
      expect(srv.requests.length).toBe(2);
      expect(srv.requests[1]).toBe('{"clientKey":"<your capmonster.cloud API key>","taskId":1234567}');

      // Let time pass to prove the cancelled loop never polls again.
      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(srv.requests.length).toBe(2);
    } finally {
      await srv.destroy();
    }
  });

  it('should return Cancelled when the caller aborts an in-flight getTaskResult', async () => {
    expect.assertions(5);

    const srv = await createControllableMock({ pollStatus: 'processing', holdPoll: true });

    try {
      const cmcClient = createClient(srv.port);
      const abortController = new AbortController();

      const solvePromise = cmcClient.Solve(createRecaptchaV2Request(), fastTimeouts, abortController);

      // The getTaskResult request is in flight and its response is held by the mock.
      await srv.waitForRequestCount(2);
      abortController.abort();
      // Releasing afterwards must not turn the aborted request into a completed poll.
      srv.releaseNextPoll();

      const task = await solvePromise;

      expect(task).toBeInstanceOf(CaptchaResult);
      expect(task.solution).toBeUndefined();
      expect(task).toHaveProperty('error', ErrorType.Cancelled);
      // The aborted request must not be retried by the polling loop.
      expect(srv.requests.length).toBe(2);

      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(srv.requests.length).toBe(2);
    } finally {
      await srv.destroy();
    }
  });

  it('should still return Timeout when the internal whole timeout expires', async () => {
    expect.assertions(3);

    const srv = await createControllableMock({ pollStatus: 'processing' });

    try {
      const cmcClient = createClient(srv.port);
      // No external AbortController: only the internal timeout can end the polling.
      const task = await cmcClient.Solve(createRecaptchaV2Request(), {
        firstRequestDelay: 0,
        firstRequestNoCacheDelay: 0,
        requestsInterval: 30,
        timeout: 300,
      });

      expect(task).toBeInstanceOf(CaptchaResult);
      expect(task.solution).toBeUndefined();
      expect(task).toHaveProperty('error', ErrorType.Timeout);
    } finally {
      await srv.destroy();
    }
  });

  it('should keep the solution when abort arrives at the same time as a ready result', async () => {
    expect.assertions(6);

    const srv = await createControllableMock({ pollStatus: 'ready', holdPoll: true });

    try {
      const cmcClient = createClient(srv.port);
      const abortController = new AbortController();

      const solvePromise = cmcClient.Solve(createRecaptchaV2Request(), fastTimeouts, abortController);

      // Wait until the getTaskResult request is in flight, then release the held ready response
      // and let it fully settle: Solve returns the Completed result before re-checking the abort flag.
      await srv.waitForRequestCount(2);
      srv.releaseNextPoll();
      const task = await solvePromise;

      // Abort in the same moment the result has arrived, immediately after the promise settles.
      abortController.abort();

      expect(abortController.signal.aborted).toBe(true);
      expect(task).toBeInstanceOf(CaptchaResult);
      expect(task.error).toBeUndefined();
      expect(task).toHaveProperty('solution.gRecaptchaResponse', 'answer');
      // Exactly one getTaskResult poll: no further requests after the completed result.
      expect(srv.requests.length).toBe(2);
      expect(srv.requests[1]).toBe('{"clientKey":"<your capmonster.cloud API key>","taskId":1234567}');
    } finally {
      await srv.destroy();
    }
  });

  it('should not rewrite an already delivered solution when the controller is aborted afterwards', async () => {
    expect.assertions(4);

    const srv = await createControllableMock({ pollStatus: 'ready' });

    try {
      const cmcClient = createClient(srv.port);
      const abortController = new AbortController();

      const task = await cmcClient.Solve(createRecaptchaV2Request(), fastTimeouts, abortController);

      // Abort only after Solve has already resolved with the completed solution.
      abortController.abort();

      expect(abortController.signal.aborted).toBe(true);
      expect(task).toBeInstanceOf(CaptchaResult);
      expect(task.error).toBeUndefined();
      expect(task).toHaveProperty('solution.gRecaptchaResponse', 'answer');
    } finally {
      await srv.destroy();
    }
  });
});
