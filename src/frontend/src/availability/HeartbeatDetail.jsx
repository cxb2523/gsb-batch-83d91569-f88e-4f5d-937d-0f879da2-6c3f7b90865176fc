// The per-attempt detail behind a check's latest heartbeat bars. The backend keeps only the most recent heartbeat
// per (check, server); a heartbeat without detail is shown as "No details", never as an empty success.
import { useEffect, useState } from 'react'
import { apiRequest } from '../api.js'
import { NO_DETAILS, errorLabel, slotHeartbeats } from './heartbeatLogic.js'

function useHeartbeats(checkId, open, refreshedAt) {
  const [data, setData] = useState(null)
  useEffect(() => {
    if (!open) return undefined
    let active = true
    apiRequest(`/availability/checks/${checkId}/heartbeats`, { method: 'GET' })
      .then((answer) => { if (active) setData(answer) })
      .catch(() => { if (active) setData({ heartbeats: [] }) })
    return () => { active = false }
  }, [checkId, open, refreshedAt])
  return data
}

function AttemptRow({ attempt }) {
  return (
    <li className="grid grid-cols-[28px_1fr_auto] items-baseline gap-2 py-1 text-xs">
      <span className="text-muted tabular-nums">#{attempt.attempt}</span>
      {attempt.ok ? (
        <>
          <span className="text-paper">{attempt.basis || 'OK'}</span>
          <span className="text-muted tabular-nums">{attempt.response_ms != null ? `${attempt.response_ms} ms` : ''}</span>
        </>
      ) : (
        <>
          <span className="text-signal">{errorLabel(attempt.error_category)}{attempt.detail ? ` · ${attempt.detail}` : ''}</span>
          <span className="text-muted tabular-nums">{attempt.response_ms != null ? `${attempt.response_ms} ms` : ''}</span>
        </>
      )}
    </li>
  )
}

export default function HeartbeatDetail({ check, open, onClose, refreshedAt }) {
  const data = useHeartbeats(check.id, open, refreshedAt)
  if (!open) return null
  const rows = slotHeartbeats(data || {})
  return (
    <div className="mt-3 rounded border border-line bg-raised/50 px-4 py-3" data-testid="heartbeat-detail">
      <div className="flex items-center justify-between gap-3">
        <h4 className="m-0 text-[13px] font-semibold text-paper">Latest heartbeat · per-attempt detail</h4>
        <button type="button" className="btn btn-sm" onClick={onClose} aria-label="Close heartbeat detail">Close</button>
      </div>
      <p className="mb-0 mt-1 text-[11px] text-muted">Only the most recent heartbeat from each server keeps its attempts; older bars are summarised into the strip.</p>
      {!data ? <p className="mb-0 mt-2 text-xs text-muted">Loading…</p> : (
        <ul className="m-0 mt-2 list-none divide-y divide-line p-0">
          {rows.map((row) => (
            <li key={row.server} className="py-2">
              <div className="flex flex-wrap items-baseline gap-2 text-xs">
                <span className="font-semibold text-paper">{row.server}</span>
                {row.hasDetails ? (
                  <span className="text-muted">{row.label}</span>
                ) : (
                  <span className="text-warn">{NO_DETAILS}</span>
                )}
              </div>
              {row.hasDetails && (
                <ul className="m-0 mt-1 list-none p-0">
                  {row.attempts.map((attempt) => <AttemptRow key={attempt.attempt} attempt={attempt} />)}
                </ul>
              )}
            </li>
          ))}
          {!rows.length && <li className="py-2 text-xs text-muted">No heartbeat reported yet.</li>}
        </ul>
      )}
    </div>
  )
}
