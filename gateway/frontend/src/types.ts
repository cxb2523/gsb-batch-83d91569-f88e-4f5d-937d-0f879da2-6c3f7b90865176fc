export interface Node {
  name: string
  provider: string
  type: string
  alive: boolean
  tested: boolean
  delay: number
  checked_at: string | null
  history: number[]
  stale: boolean
  samples: number
  success_rate: number | null
  median_delay: number | null
  jitter: number | null
}
export interface Provider {
  id: string
  label: string
  host: string
  local: boolean
  count: number
  alive: number
  updated_at: string | null
}
export interface Connection {
  id: string
  host: string
  port: string
  source: string
  process: string
  network: string
  inbound: string
  chains: string[]
  rule: string
  upload: number
  download: number
  start: string
}
export interface Snapshot {
  timestamp: number
  version: string
  health_check: { url: string; unified_delay: boolean; full_interval: number; exit_interval: number }
  policy: { mode: 'auto' | 'manual'; ready: boolean; optimized: boolean; latency_tolerance_ms: number; node: string; provider: string | null; delay: number | null; manual_node: string }
  providers: Provider[]
  nodes: Node[]
  connections: Connection[]
  totals: { upload: number; download: number }
}

export interface ProbeStatus {
  status: 'idle' | 'running' | 'done' | 'error' | 'cancelled'
  scope: 'current' | 'page' | 'provider' | 'all' | null
  total: number
  completed: number
  passed: number
  failed: number
  cooldown_seconds: number
  error: string | null
}
