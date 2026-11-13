export type DecodoTarget = 'universal';

export interface DecodoScrapeRequest {
  target: DecodoTarget;
  url: string;
  locale?: string;
  headless?: 'html' | 'png';
  markdown?: boolean;
}

export interface DecodoScrapeResponse {
  status: number;
  url: string;
  content: unknown;
  target: DecodoTarget;
}

export type TimeRange = 'day' | 'week' | 'month' | 'year';

export interface StackOverflowQuestion {
  id: string;
  title: string;
  author: string;
  score: number;
  answerCount: number;
  viewCount: number;
  tags: string[];
  url: string;
  excerpt: string;
  createdAt?: number;
}

export interface StackOverflowAnswer {
  id: string;
  author: string;
  body: string;
  score: number;
  isAccepted: boolean;
}

export interface StackOverflowComment {
  id: string;
  author: string;
  body: string;
  score: number;
}

export interface StackOverflowQuestionDetail extends StackOverflowQuestion {
  body: string;
  answers: StackOverflowAnswer[];
  comments: StackOverflowComment[];
  acceptedAnswerCount: number;
  acceptedAnswerId?: string;
  uniqueAnswerAuthorCount: number;
}

export type DeepDiveOutcome = 'success' | 'failure';

/**
 * Result of the full single-question retry loop (up to three browser attempts).
 * `attempts` is the 1-based attempt that produced `detail`.
 */
export interface DeepDiveScrapeResult {
  detail: StackOverflowQuestionDetail;
  attempts: number;
}

/**
 * Single-question deep dive entry point used by the batch flow. The default
 * implementation wraps {@link DecodoService.scrapeQuestion} and its retry loop;
 * tests inject a fake to avoid real proxy/browser access.
 */
export type DeepDiveScraper = (url: string, signal?: AbortSignal) => Promise<DeepDiveScrapeResult>;

export interface DeepDiveQuestionRecord {
  url: string;
  /** Numeric id extracted from /questions/<digits>; falls back to the raw URL. */
  questionId: string;
  outcome: DeepDiveOutcome;
  /** Attempt that succeeded (1-3), or 3 when every attempt failed. */
  attempts: number;
  /** Existing error message, present only when outcome is 'failure'. */
  reason?: string;
  /** Parsed question thread, present only when outcome is 'success'. */
  detail?: StackOverflowQuestionDetail;
}

export interface DeepDiveNotStartedRecord {
  url: string;
  questionId: string;
  outcome: 'not_started';
  reason: string;
}

export interface DeepDiveBatchResult {
  /** One record per question that actually ran, in input order. */
  records: DeepDiveQuestionRecord[];
  /** Questions that were never started because the AbortSignal fired mid-batch. */
  notStarted: DeepDiveNotStartedRecord[];
  total: number;
  succeeded: number;
  failed: number;
}

export interface StackOverflowSearchParams {
  query: string;
  tags?: string[];
  startDate: string;
  endDate: string;
  limit?: number;
}
