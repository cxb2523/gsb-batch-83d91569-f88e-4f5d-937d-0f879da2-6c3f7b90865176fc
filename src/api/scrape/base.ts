import { API_ENDPOINT, DEFAULT_CONCURRENCY } from '../../utils/constants.js';
import { getLogger } from '../../utils/logger.js';
import { Transport, assertResponse } from '../../core/transport.js';
import { dropEmptyKeys, parseJSON, parseResponse } from '../../utils/misc.js';
import { SnapshotMetaResponseSchema } from '../../schemas/responses.js';
import { ScrapeJob } from './job.js';
import { PromisePool } from '@supercharge/promise-pool';
import { Deadline } from '../../utils/deadline.js';
import { NetworkTimeoutError, TimeoutError } from '../../utils/errors.js';
import type {
    DatasetOptions,
    OrchestrateOptions,
    UnknownRecord,
    SnapshotFormat,
    SnapshotOperations,
} from '../../types/datasets.js';
import { ScrapeResult } from '../../models/result.js';

interface WebhookDisabled {
    notify: undefined;
}

interface WebhookEnabled {
    notify: string;
    endpoint: string;
    auth_header?: string;
    uncompressed_webhook?: boolean;
}

type WebhookSettings = WebhookEnabled | WebhookDisabled;

interface DatasetsQueryParamsSync {
    dataset_id: string;
    custom_output_fields?: string;
    include_errors?: boolean;
    format?: SnapshotFormat;
}

type DatasetsQueryParamsAsync = DatasetsQueryParamsSync & {
    type?: 'discover_new';
    discover_by?: string;
    limit_per_input?: number;
    limit_multiple_results?: number;
} & WebhookSettings;

interface DatasetsQueryBodySync {
    input: UnknownRecord[];
    custom_output_fields?: string;
}

type DatasetsQueryBodyAsync = UnknownRecord[];

export interface BaseAPIOptions {
    transport: Transport;
    snapshotOps?: SnapshotOperations;
}

export class BaseAPI {
    protected name!: string;
    protected logger!: ReturnType<typeof getLogger>;
    protected transport: Transport;
    protected snapshotOps?: SnapshotOperations;

    constructor(opts: BaseAPIOptions) {
        this.transport = opts.transport;
        this.snapshotOps = opts.snapshotOps;
    }

    init() {
        this.logger = getLogger(`api.scrape.${this.name}`);
    }

    #getRequestBody(
        input: UnknownRecord[],
        opt: DatasetOptions,
    ): DatasetsQueryBodySync | DatasetsQueryBodyAsync {
        return opt.async ? input : { input };
    }

    #getRequestQuery(
        datasetId: string,
        opt: DatasetOptions,
    ): DatasetsQueryParamsSync | DatasetsQueryParamsAsync {
        let res: DatasetsQueryParamsAsync | DatasetsQueryParamsSync;

        if (opt.async) {
            res = {
                dataset_id: datasetId,
                custom_output_fields: opt.customOutputFields,
                include_errors: opt.includeErrors,
                format: opt.format,
                discover_by: opt.discoverBy,
                type: opt.type,
                limit_per_input: opt.limitPerInput,
                limit_multiple_results: opt.limitMultipleResults,
                notify: opt.notify,
                endpoint: opt.endpoint,
                auth_header: opt.authHeader,
                uncompressed_webhook: opt.uncompressedWebhook,
            };
        } else {
            res = {
                dataset_id: datasetId,
                custom_output_fields: opt.customOutputFields,
                include_errors: opt.includeErrors,
                format: opt.format,
            };
        }

        dropEmptyKeys(res as Record<keyof DatasetsQueryParamsSync, unknown>);

        return res;
    }

    protected async run(
        val: UnknownRecord[],
        datasetId: string,
        opt: DatasetOptions,
    ) {
        const body = this.#getRequestBody(val, opt);

        const endpoint = opt.async
            ? API_ENDPOINT.SCRAPE_ASYNC
            : API_ENDPOINT.SCRAPE_SYNC;

        const response = await this.transport.request(endpoint, {
            method: 'POST',
            query: this.#getRequestQuery(
                datasetId,
                opt,
            ) as unknown as Record<string, unknown>,
            body: JSON.stringify(body),
        });

        const responseTxt = await assertResponse(response);

        if (opt.async || response.statusCode === 202) {
            if (response.statusCode === 202 && !opt.async) {
                this.logger.info(
                    'request exceeded sync request timeout, converted to async',
                );
            }
            const meta = parseResponse(responseTxt, SnapshotMetaResponseSchema, 'datasets/v3/trigger');
            return new ScrapeJob(meta.snapshot_id, this.snapshotOps!, {
                platform: this.name,
            });
        }

        if (opt.format === 'json') {
            return parseJSON<UnknownRecord[]>(responseTxt);
        }

        return responseTxt;
    }

    /**
     * Trigger, poll, and fetch results in a single call.
     * Platform API methods delegate to this for one-call orchestration.
     *
     * Equivalent to Python's WorkflowExecutor.execute().
     *
     * @param input - Array of input records (URLs, filters, etc.)
     * @param datasetId - Bright Data dataset identifier
     * @param opts - Orchestration options (poll interval, timeout, format)
     * @returns Promise resolving with a ScrapeResult
     */
    protected async orchestrate(
        input: UnknownRecord[],
        datasetId: string,
        opts?: OrchestrateOptions,
    ): Promise<ScrapeResult> {
        const job = (await this.run(input, datasetId, {
            async: true,
            format: opts?.format,
        })) as ScrapeJob;

        return job.toResult({
            pollInterval: opts?.pollInterval,
            pollTimeout: opts?.pollTimeout,
            onStatus: opts?.onStatus,
        });
    }

    /**
     * Trigger, poll, and fetch each input record independently.
     *
     * Unlike {@link orchestrate}, which treats the whole batch as a single
     * snapshot, this triggers one snapshot per record and never lets one
     * record's failure abort the others. Every record resolves to its own
     * {@link ScrapeResult} (with `url` set to the original input), so
     * successful data is preserved alongside per-record failure reasons.
     *
     * Each record reuses {@link ScrapeJob.toResult}, so single-record
     * timeouts are reported as `status: 'timeout'` and the
     * "status ready but fetch not ready" race keeps being retried.
     *
     * A single {@link Deadline} is shared across the whole batch: the total
     * timeout covers the entire batch rather than restarting per record, and
     * records still waiting when the budget is exhausted finish as timeouts.
     *
     * @param records - Input records (already mapped to `{ url }` form)
     * @param datasetId - Bright Data dataset identifier
     * @param opts - Orchestration options (poll interval, total timeout, format)
     * @returns One ScrapeResult per record, in the same order as `records`
     */
    protected async orchestrateBatch(
        records: UnknownRecord[],
        datasetId: string,
        opts?: OrchestrateOptions,
    ): Promise<ScrapeResult[]> {
        const pollTimeout = opts?.pollTimeout ?? 600_000;
        // One deadline for the whole batch: every record draws from the same
        // remaining budget, so the total timeout is not re-counted per record.
        const deadline = new Deadline(pollTimeout);

        const settleOne = async (
            record: UnknownRecord,
        ): Promise<ScrapeResult> => {
            const url = typeof record.url === 'string' ? record.url : '';
            let job: ScrapeJob;
            try {
                job = (await this.run([record], datasetId, {
                    async: true,
                    format: opts?.format,
                })) as ScrapeJob;
            } catch (e: unknown) {
                // A failed trigger for one record must not sink the batch.
                const isTimeout =
                    e instanceof TimeoutError ||
                    e instanceof NetworkTimeoutError;
                return new ScrapeResult({
                    success: false,
                    url,
                    error: (e as Error).message,
                    status: isTimeout ? 'timeout' : 'error',
                    platform: this.name,
                    triggerSentAt: new Date(),
                    dataFetchedAt: new Date(),
                });
            }

            const result = await job.toResult({
                pollInterval: opts?.pollInterval,
                pollTimeout: deadline.remaining,
                onStatus: opts?.onStatus,
            });
            return this.#withUrl(result, url);
        };

        const { results } = await PromisePool.for(records)
            .withConcurrency(DEFAULT_CONCURRENCY)
            .useCorrespondingResults()
            .process(settleOne);

        // settleOne never rejects, so every slot holds a ScrapeResult; guard
        // against the pool's failure symbols defensively anyway.
        return results.map((value, i) => {
            if (value instanceof ScrapeResult) return value;
            const record = records[i];
            const url =
                record && typeof record.url === 'string' ? record.url : '';
            return new ScrapeResult({
                success: false,
                url,
                error: 'batch item failed to complete',
                status: 'error',
                platform: this.name,
                triggerSentAt: new Date(),
                dataFetchedAt: new Date(),
            });
        });
    }

    /**
     * Return a copy of a per-record ScrapeResult carrying the original URL.
     * ScrapeJob.toResult() cannot know the input URL (one snapshot may cover
     * many inputs), so the batch layer attaches it here.
     */
    #withUrl(result: ScrapeResult, url: string): ScrapeResult {
        return new ScrapeResult({
            success: result.success,
            data: result.data,
            error: result.error,
            cost: result.cost,
            url,
            status: result.status,
            snapshotId: result.snapshotId,
            platform: result.platform,
            method: result.method,
            rowCount: result.rowCount,
            triggerSentAt: result.triggerSentAt,
            dataFetchedAt: result.dataFetchedAt,
        });
    }
}
