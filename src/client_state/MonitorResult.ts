export interface MonitorSchedule {
  frequency?: string | null;
  cron?: string | null;
  timezone?: string | null;
  next_run_at?: string | null;
}

export interface MonitorNotificationChannel {
  type: string; // 'email' | 'slack' | 'sms'
  target: string;
  events?: string[] | null;
}

export interface MonitorNotification {
  events?: string[] | null;
  channels?: MonitorNotificationChannel[] | null;
}

export interface MonitorWebhook {
  url: string;
}

export interface MonitorLastRun {
  id: string;
  status: string; // 'completed' | 'failed'
  change_detected: boolean;
  ran_at?: string | null;
}

export interface MonitorTracked {
  type?: string | null;
  urls?: string[] | null;
  web_query?: string | null;
}

export interface MonitorSourcePolicy {
  include_urls?: string[] | null;
  exclude_urls?: string[] | null;
  include_domains?: string[] | null;
  exclude_domains?: string[] | null;
}

export interface MonitorEvent {
  id: string;
  run_id?: string | null;
  created?: number | null;
  changed?: boolean | null;
  summary?: string | null;
  snapshot_url?: string | null;
}

/** Result for a single monitor (create / get / update / pause / resume / delete). */
export class MonitorResult {
  public readonly id: string;
  public readonly object: string;
  public readonly query: string;
  public readonly status: string;
  public readonly tracked?: MonitorTracked | null;
  public readonly source_policy?: MonitorSourcePolicy | null;
  public readonly schedule?: MonitorSchedule | null;
  public readonly notification?: MonitorNotification | null;
  public readonly webhook?: MonitorWebhook | null;
  public readonly output_schema?: Record<string, unknown> | null;
  public readonly metadata: Record<string, unknown>;
  public readonly last_run?: MonitorLastRun | null;
  public readonly total_count?: number | null;
  public readonly mermaid_diagram?: string | null;
  public readonly error_message?: string | null;
  public readonly created?: number | null;
  public readonly updated?: number | null;

  [key: string]: unknown;

  constructor(data: Record<string, unknown>) {
    this.id = data.id as string;
    this.object = (data.object as string) ?? 'monitor';
    this.query = data.query as string;
    this.status = data.status as string;
    this.tracked = (data.tracked as MonitorTracked | null) ?? null;
    this.source_policy = (data.source_policy as MonitorSourcePolicy | null) ?? null;
    this.schedule = (data.schedule as MonitorSchedule | null) ?? null;
    this.notification = (data.notification as MonitorNotification | null) ?? null;
    this.webhook = (data.webhook as MonitorWebhook | null) ?? null;
    this.output_schema = (data.output_schema as Record<string, unknown> | null) ?? null;
    this.metadata = (data.metadata as Record<string, unknown>) ?? {};
    this.last_run = (data.last_run as MonitorLastRun | null) ?? null;
    this.total_count = (data.total_count as number | null) ?? null;
    this.mermaid_diagram = (data.mermaid_diagram as string | null) ?? null;
    this.error_message = (data.error_message as string | null) ?? null;
    this.created = (data.created as number | null) ?? null;
    this.updated = (data.updated as number | null) ?? null;
  }

  public toString(): string {
    const q = this.query.length > 60 ? this.query.slice(0, 60) + '...' : this.query;
    const freq = this.schedule?.frequency ? `, frequency=${this.schedule.frequency}` : '';
    return `MonitorResult(id=${this.id}, status=${this.status}${freq}, query=${q})`;
  }
}

/** Result for GET /monitors (list). */
export class MonitorListResult {
  public readonly monitors: MonitorResult[];
  public readonly count: number;

  constructor(data: Record<string, unknown>) {
    const raw = (data.monitors as Record<string, unknown>[]) ?? [];
    this.monitors = raw.map((m) => new MonitorResult(m));
    this.count = (data.count as number) ?? 0;
  }

  public [Symbol.iterator]() {
    return this.monitors[Symbol.iterator]();
  }

  public toString(): string {
    return `MonitorListResult(count=${this.count})`;
  }
}

/** Result for GET /monitors/{id}/events. */
export class MonitorEventResult {
  public readonly data: MonitorEvent[];
  public readonly has_more: boolean;
  public readonly next_cursor?: string | null;
  public readonly total_count?: number | null;

  constructor(data: Record<string, unknown>) {
    this.data = (data.data as MonitorEvent[]) ?? [];
    this.has_more = (data.has_more as boolean) ?? false;
    this.next_cursor = (data.next_cursor as string | null) ?? null;
    this.total_count = (data.total_count as number | null) ?? null;
  }

  public [Symbol.iterator]() {
    return this.data[Symbol.iterator]();
  }

  public toString(): string {
    const more = this.has_more ? ', has_more=true' : '';
    return `MonitorEventResult(events=${this.data.length}${more})`;
  }
}
