/**
 * Presentation helpers for webhook delivery rows.
 *
 * These encode NO delivery policy: the backoff ladder, the max-attempts
 * cutoff, the private-network block, and the claim window are all decided
 * by the runner/API and recorded on the webhook_deliveries row. Everything
 * here is a pure read of those recorded fields so the run page can present
 * them verbatim.
 */
import type { WebhookDelivery } from './api';

/**
 * A delivery is terminal when no further attempts will happen — anything
 * but PENDING ('DELIVERED' | 'FAILED'). Terminal rows must never show a
 * "next retry" time, even if a stale nextRetryAt were somehow present.
 */
export function isTerminalDelivery(status: string): boolean {
  return status !== 'PENDING';
}

/**
 * The next retry instant to display, or null when there is none to show.
 * Only a PENDING delivery can have a scheduled retry; the runner nulls
 * next_retry_at on every terminal transition, and this helper refuses to
 * surface one for terminal rows regardless.
 */
export function displayNextRetryAt(
  d: Pick<WebhookDelivery, 'status' | 'nextRetryAt'>
): string | null {
  if (isTerminalDelivery(d.status)) return null;
  return d.nextRetryAt;
}

/**
 * One-line human summary of where a delivery stands:
 *   PENDING   → when the next attempt fires (server-scheduled)
 *   FAILED    → why it terminated (the runner records the reason in
 *               responseBody: private-network block, webhook/run deleted,
 *               last HTTP/network error once retries are exhausted)
 *   DELIVERED → when it completed
 */
export function deliveryStatusLine(
  d: Pick<WebhookDelivery, 'status' | 'nextRetryAt' | 'responseBody' | 'finishedAt'>
): string {
  if (d.status === 'PENDING') {
    const at = displayNextRetryAt(d);
    return at ? `next retry · ${new Date(at).toLocaleString()}` : 'retry pending';
  }
  if (d.status === 'FAILED') {
    const reason = d.responseBody?.trim();
    return reason ? `terminated · ${reason}` : 'terminated · no further retries';
  }
  if (d.status === 'DELIVERED') {
    return d.finishedAt
      ? `delivered · ${new Date(d.finishedAt).toLocaleString()}`
      : 'delivered';
  }
  return d.status;
}
