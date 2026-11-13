// Pure helpers for the per-attempt detail a collector reports with each check heartbeat.
// The backend stores one heartbeat per (check, server); a heartbeat without detail is "no details", never an
// empty success, so these helpers treat missing attempts as unknown rather than ok.

// Human-readable labels for the collector's fixed failure vocabulary. Unknown values fall back to themselves.
export const ERROR_LABELS = {
  timeout: 'Timeout',
  connection_refused: 'Connection refused',
  connection_reset: 'Connection reset',
  dns_error: 'DNS resolution failed',
  certificate_error: 'Certificate problem',
  tls_error: 'TLS handshake failed',
  http_status: 'Unexpected HTTP status',
  assertion_mismatch: 'Assertion mismatch',
  invalid_response: 'Invalid response',
  icmp_denied: 'ICMP not permitted',
  network_error: 'Network error',
  error: 'Check error',
}

export const NO_DETAILS = 'No details'

export function errorLabel(category) {
  return ERROR_LABELS[category] || category || 'Error'
}

// One attempt as a short line: "1 · OK · 42 ms · HTTP 200 accepted" or "2 · Timeout · Timed out after 5 s".
export function describeAttempt(attempt) {
  if (!attempt || typeof attempt !== 'object') return ''
  const index = Number(attempt.attempt) || 0
  if (attempt.ok) {
    const ms = Number.isFinite(attempt.response_ms) ? `${attempt.response_ms} ms` : null
    return [index, 'OK', ms, attempt.basis].filter((part) => part !== null && part !== undefined && part !== '').join(' · ')
  }
  return [index, errorLabel(attempt.error_category), attempt.detail].filter((part) => part !== null && part !== undefined && part !== '').join(' · ')
}

// What one server's latest heartbeat should display. has_details false means an older collector sent no detail.
export function heartbeatView(heartbeat) {
  if (!heartbeat || heartbeat.has_details === false || !Array.isArray(heartbeat.attempts) || heartbeat.attempts.length === 0) {
    return { hasDetails: false, label: NO_DETAILS, attempts: [] }
  }
  return {
    hasDetails: true,
    label: `${heartbeat.attempts.length} attempt${heartbeat.attempts.length === 1 ? '' : 's'}`,
    attempts: heartbeat.attempts.map((attempt) => ({ ...attempt, line: describeAttempt(attempt) })),
  }
}

// The attempts to show for a clicked slot: each known server in stable order, each explicitly marked when unknown.
export function slotHeartbeats(data) {
  if (!data || !Array.isArray(data.heartbeats)) return []
  return data.heartbeats.map((heartbeat) => ({ server: heartbeat.hostname || `server ${heartbeat.server_id}`, ...heartbeatView(heartbeat) }))
}
