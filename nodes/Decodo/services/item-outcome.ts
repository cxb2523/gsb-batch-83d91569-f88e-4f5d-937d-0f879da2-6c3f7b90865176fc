import { IDataObject, INodeExecutionData } from 'n8n-workflow';
import { ItemErrorSource, ItemStatus, RETRY_LIST_FIELD } from '../types';

/** Reason attached to items that are skipped because they are not in the retry list. */
export const NOT_IN_RETRY_LIST_REASON =
  'Not listed in the retry list of a previous run, so no request was made.';

const asMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return String(error);
};

const toIndex = (entry: unknown): number | null => {
  const index = typeof entry === 'number' ? entry : Number(entry);

  return Number.isInteger(index) && index >= 0 ? index : null;
};

/**
 * Reads the retry list left behind by a previous run.
 *
 * The list lives under the `retryList` field on the input items and holds the
 * indexes of the items that failed, where index `n` identifies the `n`-th input
 * item. Every output item of a run carries the same field, so the output can be
 * fed back into the node unchanged.
 *
 * Returns `null` when no input item carries such a list, which means the node
 * runs in normal mode and processes every item. An empty list is a retry run in
 * which nothing needs to be fetched.
 */
export const extractRetryList = (items: INodeExecutionData[]): number[] | null => {
  const indexes = new Set<number>();
  let hasRetryList = false;

  for (const item of items) {
    const value = ((item?.json ?? {}) as Record<string, unknown>)[RETRY_LIST_FIELD];

    if (!Array.isArray(value)) {
      continue;
    }

    hasRetryList = true;

    for (const entry of value) {
      const index = toIndex(entry);

      if (index !== null) {
        indexes.add(index);
      }
    }
  }

  if (!hasRetryList) {
    return null;
  }

  return [...indexes].sort((left, right) => left - right);
};

/**
 * Decides whether the input item at `position` has to be fetched in a retry run.
 *
 * Positions are the indexes the retry list refers to, so an out-of-range entry
 * simply matches no item and never triggers a request.
 */
export const isInRetryList = (position: number, retryIndexes: Set<number> | null): boolean =>
  retryIndexes === null || retryIndexes.has(position);

/** Reads the target of an item without performing any request. */
export const readTarget = (
  item: INodeExecutionData | undefined,
  nodeParameters?: Record<string, unknown>,
): string | null => {
  const fromParameters = nodeParameters?.operation;
  const fromJson = (item?.json as Record<string, unknown> | undefined)?.target;

  if (typeof fromParameters === 'string' && fromParameters !== '') {
    return fromParameters;
  }

  return typeof fromJson === 'string' && fromJson !== '' ? fromJson : null;
};

export const buildSuccessOutcome = ({
  index,
  target,
  response,
}: {
  index: number;
  target: string | null;
  response: unknown;
}): INodeExecutionData => ({
  json: {
    index,
    target,
    status: ItemStatus.SUCCESS,
    response: response as IDataObject,
  },
  pairedItem: index,
});

export const buildFailedOutcome = ({
  index,
  target,
  error,
  source,
  statusCode,
}: {
  index: number;
  target: string | null;
  error: unknown;
  source: ItemErrorSource;
  statusCode?: string | number | null;
}): INodeExecutionData => ({
  json: {
    index,
    target,
    status: ItemStatus.FAILED,
    error: asMessage(error),
    errorSource: source,
    ...(statusCode !== undefined && statusCode !== null && { statusCode }),
  },
  pairedItem: index,
});

export const buildSkippedOutcome = ({
  index,
  target,
  reason = NOT_IN_RETRY_LIST_REASON,
}: {
  index: number;
  target: string | null;
  reason?: string;
}): INodeExecutionData => ({
  json: {
    index,
    target,
    status: ItemStatus.SKIPPED,
    skipReason: reason,
  },
  pairedItem: index,
});

/**
 * Attaches the list of indexes that failed in this run to every outcome, so any
 * output item can be fed back as the retry list of the next run. The list is
 * empty when nothing failed, which makes a following run skip every item.
 */
export const attachRetryList = (outcomes: INodeExecutionData[]): INodeExecutionData[] => {
  const failedIndexes = outcomes
    .filter((outcome) => outcome.json.status === ItemStatus.FAILED)
    .map((outcome) => outcome.json.index as number)
    .sort((left, right) => left - right);

  for (const outcome of outcomes) {
    outcome.json[RETRY_LIST_FIELD] = failedIndexes;
  }

  return outcomes;
};

export const asStatusCode = (error: unknown): string | number | null => {
  const candidate =
    (error as { statusCode?: unknown })?.statusCode ?? (error as { httpCode?: unknown })?.httpCode;

  return typeof candidate === 'string' || typeof candidate === 'number' ? candidate : null;
};
