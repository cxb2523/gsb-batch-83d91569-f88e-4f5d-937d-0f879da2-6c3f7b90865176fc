import { DecodoService } from './decodo.service';
import type {
  DeepDiveScrapeResult,
  DeepDiveScraper,
  StackOverflowQuestionDetail,
} from './decodo.types';

function buildDetail(url: string, id: string): StackOverflowQuestionDetail {
  return {
    id,
    title: `Question ${id}`,
    author: 'jane-dev',
    score: 7,
    answerCount: 1,
    viewCount: 0,
    tags: ['javascript'],
    url,
    excerpt: 'excerpt',
    body: 'body with more than fifty characters of usable question content here',
    answers: [
      {
        id: `${id}-answer-1`,
        author: 'john-dev',
        body: 'answer body',
        score: 3,
        isAccepted: true,
      },
    ],
    comments: [{ id: `${id}-comment-1`, author: 'reader', body: 'comment body', score: 1 }],
    acceptedAnswerCount: 1,
    acceptedAnswerId: `${id}-answer-1`,
    uniqueAnswerAuthorCount: 1,
  };
}

function buildService(): DecodoService {
  // SettingsService is only used when a real browser is launched, which the
  // injected fake scraper guarantees never happens in these tests.
  const service = Object.create(DecodoService.prototype) as DecodoService;
  return service;
}

describe('DecodoService.scrapeQuestions', () => {
  const url1 = 'https://stackoverflow.com/questions/10000001/first-question';
  const url2 = 'https://stackoverflow.com/questions/10000002/second-question';
  const url3 = 'https://stackoverflow.com/questions/10000003/third-question';

  it('resolves every question successfully and keeps input order', async () => {
    const service = buildService();
    const calls: Array<{ url: string; signal?: AbortSignal }> = [];
    const fakeScraper: DeepDiveScraper = jest.fn((url, signal) => {
      calls.push({ url, signal });
      const id = url.match(/\/questions\/(\d+)/)?.[1] ?? 'unknown';
      return Promise.resolve<DeepDiveScrapeResult>({
        detail: buildDetail(url, id),
        attempts: 1,
      });
    });
    const signal = new AbortController().signal;

    const result = await service.scrapeQuestions([url1, url2, url3], signal, fakeScraper);

    expect(fakeScraper).toHaveBeenCalledTimes(3);
    expect(calls.map((call) => call.url)).toEqual([url1, url2, url3]);
    // The caller signal is forwarded to the single-question logic.
    expect(calls.every((call) => call.signal === signal)).toBe(true);
    expect(result.total).toBe(3);
    expect(result.succeeded).toBe(3);
    expect(result.failed).toBe(0);
    expect(result.notStarted).toEqual([]);
    expect(result.records).toHaveLength(3);
    expect(result.records.map((record) => record.questionId)).toEqual([
      '10000001',
      '10000002',
      '10000003',
    ]);
    for (const record of result.records) {
      expect(record.outcome).toBe('success');
      expect(record.attempts).toBe(1);
      expect(record.reason).toBeUndefined();
      expect(record.detail?.url).toBe(record.url);
    }
  });

  it('records a three-attempt failure for one question without stopping the others', async () => {
    const service = buildService();
    const fakeScraper: DeepDiveScraper = jest.fn((url) => {
      if (url === url2) {
        return Promise.reject(
          new Error(
            'Stack Overflow deep dive failed after 3 browser attempts: ' +
              'Cloudflare challenge did not resolve within 15s',
          ),
        );
      }
      const id = url.match(/\/questions\/(\d+)/)?.[1] ?? 'unknown';
      return Promise.resolve<DeepDiveScrapeResult>({
        detail: buildDetail(url, id),
        attempts: url === url3 ? 2 : 1,
      });
    });

    const result = await service.scrapeQuestions([url1, url2, url3], undefined, fakeScraper);

    expect(fakeScraper).toHaveBeenCalledTimes(3);
    expect(result.total).toBe(3);
    expect(result.succeeded).toBe(2);
    expect(result.failed).toBe(1);
    expect(result.notStarted).toEqual([]);
    expect(result.records.map((record) => record.outcome)).toEqual([
      'success',
      'failure',
      'success',
    ]);

    const failed = result.records[1];
    expect(failed.questionId).toBe('10000002');
    expect(failed.attempts).toBe(3);
    expect(failed.detail).toBeUndefined();
    expect(failed.reason).toContain('Cloudflare challenge did not resolve within 15s');
    expect(failed.reason).toContain('failed after 3 browser attempts');

    expect(result.records[0].attempts).toBe(1);
    expect(result.records[2].attempts).toBe(2);
  });

  it('surfaces the existing error messages as failure reasons', async () => {
    const service = buildService();
    const reasons = [
      'Cloudflare challenge did not resolve within 15s',
      'Rendered Stack Overflow question did not contain enough usable content',
      'Stack Overflow deep dive failed after 3 browser attempts: some other failure',
    ];
    const fakeScraper: DeepDiveScraper = jest.fn(() => Promise.reject(new Error(reasons.shift())));

    const result = await service.scrapeQuestions([url1, url2, url3], undefined, fakeScraper);

    expect(result.succeeded).toBe(0);
    expect(result.failed).toBe(3);
    expect(result.records.map((record) => record.reason)).toEqual([
      'Cloudflare challenge did not resolve within 15s',
      'Rendered Stack Overflow question did not contain enough usable content',
      'Stack Overflow deep dive failed after 3 browser attempts: some other failure',
    ]);
    expect(result.records.every((record) => record.attempts === 3)).toBe(true);
  });

  it('keeps the raw URL as questionId when the URL has no question number', async () => {
    const service = buildService();
    const plainUrl = 'https://stackoverflow.com/questions/tagged/typescript';
    const fakeScraper: DeepDiveScraper = jest.fn((url) =>
      Promise.resolve<DeepDiveScrapeResult>({
        detail: buildDetail(url, ''),
        attempts: 3,
      }),
    );

    const result = await service.scrapeQuestions([plainUrl], undefined, fakeScraper);

    expect(result.records[0].questionId).toBe(plainUrl);
    expect(result.records[0].outcome).toBe('success');
    expect(result.records[0].attempts).toBe(3);
  });

  it('rejects without scraping anything when the signal is already aborted', async () => {
    const service = buildService();
    const controller = new AbortController();
    const abortError = new Error('cancelled before start');
    controller.abort(abortError);
    const fakeScraper: DeepDiveScraper = jest.fn();

    await expect(
      service.scrapeQuestions([url1, url2], controller.signal, fakeScraper),
    ).rejects.toBe(abortError);
    expect(fakeScraper).not.toHaveBeenCalled();

    // Also cover abort() without an explicit reason: the platform's default
    // signal reason must be propagated untouched.
    const reasonlessController = new AbortController();
    reasonlessController.abort();
    await expect(
      service.scrapeQuestions([url1], reasonlessController.signal, fakeScraper),
    ).rejects.toBe(reasonlessController.signal.reason);
    expect(fakeScraper).not.toHaveBeenCalled();
  });

  it('keeps completed records and never starts remaining questions when aborted mid-batch', async () => {
    const service = buildService();
    const controller = new AbortController();
    const fakeScraper: DeepDiveScraper = jest.fn((url) => {
      if (url === url2) {
        controller.abort(new Error('cancelled during batch'));
        return Promise.reject(new Error('Request was cancelled'));
      }
      const id = url.match(/\/questions\/(\d+)/)?.[1] ?? 'unknown';
      return Promise.resolve<DeepDiveScrapeResult>({
        detail: buildDetail(url, id),
        attempts: 1,
      });
    });

    const result = await service.scrapeQuestions(
      [url1, url2, url3],
      controller.signal,
      fakeScraper,
    );

    // url1 succeeded, url2 ran and failed, url3 was never invoked.
    expect(fakeScraper).toHaveBeenCalledTimes(2);
    expect(fakeScraper).toHaveBeenNthCalledWith(1, url1, controller.signal);
    expect(fakeScraper).toHaveBeenNthCalledWith(2, url2, controller.signal);
    expect(result.records).toHaveLength(2);
    expect(result.records.map((record) => record.outcome)).toEqual(['success', 'failure']);
    expect(result.records[1].reason).toBe('Request was cancelled');
    expect(result.notStarted).toEqual([
      {
        url: url3,
        questionId: '10000003',
        outcome: 'not_started',
        reason: 'cancelled during batch',
      },
    ]);
    expect(result.total).toBe(3);
    expect(result.succeeded).toBe(1);
    expect(result.failed).toBe(1);
  });
});
