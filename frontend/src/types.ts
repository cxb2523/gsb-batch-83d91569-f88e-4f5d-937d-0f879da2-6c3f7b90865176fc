export interface QueryProcess {
  query_id: string;
  query: string;
  elapsed: number;
  memory_usage: number;
  formatted_memory_usage: string;
  peak_memory: number;
  formatted_peak_memory: string;
  formatted_peak_memory_usage?: string;
  read_bytes: number;
  formatted_read_bytes: string;
  written_bytes: number;
  formatted_written_bytes: string;
  read_rows: number;
  written_rows: number;
  user: string;
  is_cancelled?: boolean;
}

export interface MemoryMetric {
  fqdn: string;
  metric: string;
  bytes: string | number;
  readable_size: string;
}

export type TopologyMode = 'cloud' | 'cluster' | 'single';

export type TargetState =
  | 'running'
  | 'partiallyRunning'
  | 'degraded'
  | 'idle'
  | 'stopped'
  | 'awaking'
  | 'starting'
  | 'stopping'
  | 'provisioning'
  | 'terminating'
  | 'terminated'
  | 'softDeleting'
  | 'softDeleted'
  | 'failed'
  | 'unknown';

export interface Target {
  id: string;
  name: string;
  state: TargetState;
  queryable: boolean;
  mode: TopologyMode;
  numReplicas: number | null;
  minMemoryGb: number | null;
  maxMemoryGb: number | null;
  region: string | null;
  provider: string | null;
  warehouseId: string | null;
  isPrimary: boolean | null;
  clickhouseVersion: string | null;
}

export interface ServicesPageAttempt {
  page: number;
  cursor: string | null;
  success: boolean;
  serviceCount: number;
  error: string | null;
  statusCode: number | null;
  requestId: string | null;
  hasNextPage: boolean;
  nextCursor: string | null;
  nextPage: number | null;
}

/** Per-page outcome of the Cloud services collection. Present in cloud mode only. */
export interface ServicesCollection {
  organizationId: string;
  collectedAt: string;
  /** False when collection stopped early; `targets` is then a prefix of the org's services. */
  complete: boolean;
  stoppedReason: 'page_failed' | 'repeated_cursor' | 'repeated_page' | 'max_pages' | null;
  totalServices: number;
  pages: ServicesPageAttempt[];
}

export interface Topology {
  mode: TopologyMode;
  organization: { id: string; name: string } | null;
  warehouseId: string | null;
  targets: Target[];
  fetchedAt: string;
  servicesCollection?: ServicesCollection | null;
}

export interface ProcessResponse {
  cluster: string | null;
  target?: Target;
  sleeping?: boolean;
  processes: {
    [nodeName: string]: QueryProcess[];
  };
  memory_metrics?: {
    [nodeName: string]: {
      [metric: string]: MemoryMetric;
    };
  };
}
