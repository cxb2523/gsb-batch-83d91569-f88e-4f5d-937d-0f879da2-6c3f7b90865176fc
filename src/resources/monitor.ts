import {OlostepTransport} from '../http/transport.js';
import {OlostepResource} from './base.js';
import {MonitorResult, MonitorListResult, MonitorEventResult} from '../client_state/MonitorResult.js';

const stripUndefined = <T extends Record<string, unknown>>(obj: T): Partial<T> => {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) {
      (out as Record<string, unknown>)[k] = v;
    }
  }
  return out;
};

// Sentinel so callers can pass webhook=null to explicitly remove a webhook
// while omitting the field entirely leaves it unchanged.
const UNSET = Symbol('unset');

export interface MonitorSourcePolicy {
  includeUrls?: string[];
  excludeUrls?: string[];
  includeDomains?: string[];
  excludeDomains?: string[];
}

export interface MonitorNotificationChannel {
  type: 'email' | 'slack' | 'sms';
  target: string;
  events?: ('changed' | 'first_snapshot')[];
}

export interface MonitorNotification {
  events?: ('changed' | 'first_snapshot')[];
  channels?: MonitorNotificationChannel[];
}

export interface MonitorWebhook {
  url: string;
}

export interface MonitorCreateOptions {
  /** Natural-language description of what to watch. */
  query: string;
  /**
   * How often to run. Natural language such as "every hour", "every day at 9am".
   * Minimum 10 minutes. Defaults to "every hour".
   */
  frequency?: string;
  /** Controls which URLs are fetched on each run. */
  sourcePolicy?: MonitorSourcePolicy;
  /** Where to send change alerts. */
  notification?: MonitorNotification;
  /** HTTPS endpoint that receives a POST on each run. Payloads are not signed. */
  webhook?: MonitorWebhook;
  /** Optional JSON Schema for structured extraction from the monitored page. */
  outputSchema?: Record<string, unknown>;
  /** Key/value labels for tagging this monitor. */
  metadata?: Record<string, string>;
}

export interface MonitorUpdateOptions {
  /** New schedule in natural language (e.g. "every 4 hours"). Recreates the schedule. */
  frequency?: string;
  /** Replacement notification config. */
  notification?: MonitorNotification;
  /**
   * Replacement webhook. Pass `null` explicitly to remove an existing webhook.
   * Omit to leave the webhook unchanged.
   */
  webhook?: MonitorWebhook | null;
  /** Metadata patch — empty-string values delete individual keys. */
  metadata?: Record<string, string>;
}

export interface MonitorListOptions {
  /** When true, includes soft-deleted monitors. */
  includeDeleted?: boolean;
}

export interface MonitorGetOptions {
  /** Set false to omit total_count from the response. Default: true. */
  includeTotalCount?: boolean;
  /** When true, includes a mermaid_diagram string for the workflow DAG. */
  includeDiagram?: boolean;
}

export interface MonitorEventsOptions {
  /** Number of events to return (1–100). Default: 25. */
  limit?: number;
  /** Pagination cursor from a previous response's next_cursor field. */
  cursor?: string;
  /** When true, returns only total_count without event data. */
  countOnly?: boolean;
}

export class MonitorNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  /**
   * Create a recurring web monitor.
   *
   * Provisions a shadow agent, generates a workflow spec, and schedules
   * recurring runs. Returns immediately with `status: provisioning`; transitions
   * to `active` once setup completes (usually within a minute).
   *
   * @example
   * const monitor = await client.monitors.create({
   *   query: "Watch the Stripe status page for incidents",
   *   frequency: "every hour",
   *   notification: {
   *     channels: [{ type: "email", target: "you@example.com" }]
   *   }
   * });
   */
  async create(options: MonitorCreateOptions): Promise<MonitorResult> {
    const payload = stripUndefined({
      query: options.query,
      frequency: options.frequency,
      source_policy: options.sourcePolicy
        ? stripUndefined({
            include_urls: options.sourcePolicy.includeUrls,
            exclude_urls: options.sourcePolicy.excludeUrls,
            include_domains: options.sourcePolicy.includeDomains,
            exclude_domains: options.sourcePolicy.excludeDomains,
          })
        : undefined,
      notification: options.notification,
      webhook: options.webhook,
      output_schema: options.outputSchema,
      metadata: options.metadata,
    });

    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: '/monitors',
      body: payload,
    });
    return new MonitorResult(data);
  }

  /**
   * List all monitors for this API key.
   *
   * @example
   * const result = await client.monitors.list();
   * for (const monitor of result) {
   *   console.log(monitor.id, monitor.status);
   * }
   */
  async list(options?: MonitorListOptions): Promise<MonitorListResult> {
    const query = options?.includeDeleted ? {include_deleted: 'true'} : undefined;
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'GET',
      path: '/monitors',
      query,
    });
    return new MonitorListResult(data);
  }

  /**
   * Retrieve a single monitor by ID.
   *
   * @example
   * const monitor = await client.monitors.get("monitor_abc123");
   * console.log(monitor.last_run?.change_detected);
   */
  async get(monitorId: string, options?: MonitorGetOptions): Promise<MonitorResult> {
    const query: Record<string, string> = {};
    if (options?.includeTotalCount === false) query['include_total_count'] = 'false';
    if (options?.includeDiagram) query['include-diagram'] = 'true';

    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'GET',
      path: `/monitors/${monitorId}`,
      query: Object.keys(query).length > 0 ? query : undefined,
    });
    return new MonitorResult(data);
  }

  /**
   * Update a monitor's settings.
   *
   * Only `frequency`, `notification`, `webhook`, and `metadata` are accepted.
   * Changing `frequency` recreates the underlying EventBridge schedule.
   * Pass `webhook: null` to remove a configured webhook.
   *
   * @example
   * await client.monitors.update("monitor_abc123", { frequency: "every 4 hours" });
   */
  async update(monitorId: string, options: MonitorUpdateOptions): Promise<MonitorResult> {
    const body: Record<string, unknown> = {};
    if (options.frequency !== undefined) body['frequency'] = options.frequency;
    if (options.notification !== undefined) body['notification'] = options.notification;
    if (options.metadata !== undefined) body['metadata'] = options.metadata;
    // Include webhook when explicitly set (including null for removal)
    if ('webhook' in options) body['webhook'] = options.webhook ?? null;

    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: `/monitors/${monitorId}`,
      body,
    });
    return new MonitorResult(data);
  }

  /**
   * Pause a monitor, disabling future scheduled runs.
   *
   * @example
   * await client.monitors.pause("monitor_abc123");
   */
  async pause(monitorId: string): Promise<MonitorResult> {
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: `/monitors/${monitorId}/pause`,
    });
    return new MonitorResult(data);
  }

  /**
   * Resume a paused monitor, re-enabling scheduled runs.
   *
   * @example
   * await client.monitors.resume("monitor_abc123");
   */
  async resume(monitorId: string): Promise<MonitorResult> {
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: `/monitors/${monitorId}/resume`,
    });
    return new MonitorResult(data);
  }

  /**
   * Soft-delete a monitor and remove its schedule and shadow agent.
   *
   * @example
   * await client.monitors.delete("monitor_abc123");
   */
  async delete(monitorId: string): Promise<MonitorResult> {
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'DELETE',
      path: `/monitors/${monitorId}`,
    });
    return new MonitorResult(data);
  }

  /**
   * List snapshot events for a monitor, newest first.
   *
   * @example
   * const events = await client.monitors.events("monitor_abc123");
   * for (const event of events) {
   *   console.log(event.changed, event.summary);
   * }
   */
  async events(monitorId: string, options?: MonitorEventsOptions): Promise<MonitorEventResult> {
    const query: Record<string, string | number> = {};
    if (options?.limit !== undefined) query['limit'] = options.limit;
    if (options?.cursor !== undefined) query['cursor'] = options.cursor;
    if (options?.countOnly) query['count_only'] = 'true';

    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'GET',
      path: `/monitors/${monitorId}/events`,
      query: Object.keys(query).length > 0 ? (query as Record<string, string>) : undefined,
    });
    return new MonitorEventResult(data);
  }
}
