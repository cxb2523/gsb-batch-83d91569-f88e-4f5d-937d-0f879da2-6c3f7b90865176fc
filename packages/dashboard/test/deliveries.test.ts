/**
 * Tests for the delivery presentation helpers (lib/deliveries.ts). These
 * pin the run-page contract: a delivery's next retry time is shown ONLY
 * while the row is PENDING, and terminated deliveries surface the reason
 * the runner recorded — the page never re-derives retry or blocking rules.
 */
import { describe, it, expect } from 'vitest';
import { isTerminalDelivery, displayNextRetryAt, deliveryStatusLine } from '@/lib/deliveries';

describe('isTerminalDelivery', () => {
  it('treats anything but PENDING as terminal', () => {
    expect(isTerminalDelivery('PENDING')).toBe(false);
    expect(isTerminalDelivery('DELIVERED')).toBe(true);
    expect(isTerminalDelivery('FAILED')).toBe(true);
  });
});

describe('displayNextRetryAt', () => {
  const at = '2026-10-01T10:05:00.000Z';

  it('returns the scheduled retry for a PENDING delivery', () => {
    expect(displayNextRetryAt({ status: 'PENDING', nextRetryAt: at })).toBe(at);
  });

  it('returns null for a PENDING delivery with no schedule yet', () => {
    expect(displayNextRetryAt({ status: 'PENDING', nextRetryAt: null })).toBeNull();
  });

  // A terminated delivery must never show a next retry time — even if a
  // stale nextRetryAt value were present on the row.
  it('suppresses nextRetryAt on terminal deliveries', () => {
    expect(displayNextRetryAt({ status: 'FAILED', nextRetryAt: at })).toBeNull();
    expect(displayNextRetryAt({ status: 'DELIVERED', nextRetryAt: at })).toBeNull();
  });
});

describe('deliveryStatusLine', () => {
  it('shows the next retry time while pending', () => {
    const line = deliveryStatusLine({
      status: 'PENDING',
      nextRetryAt: '2026-10-01T10:05:00.000Z',
      responseBody: 'bad gateway',
      finishedAt: null,
    });
    expect(line).toContain('next retry');
    expect(line).toContain(new Date('2026-10-01T10:05:00.000Z').toLocaleString());
  });

  it('shows the recorded termination reason once failed', () => {
    const line = deliveryStatusLine({
      status: 'FAILED',
      nextRetryAt: null,
      responseBody: 'Webhook URL targets a private/internal network address',
      finishedAt: '2026-10-01T10:00:00.000Z',
    });
    expect(line).toContain('terminated');
    expect(line).toContain('private/internal network address');
    expect(line).not.toContain('next retry');
  });

  it('covers the deleted-webhook and missing-run termination reasons', () => {
    for (const responseBody of [
      'Webhook was deleted before this delivery completed',
      'Run record no longer exists — delivery terminated',
    ]) {
      const line = deliveryStatusLine({
        status: 'FAILED',
        nextRetryAt: null,
        responseBody,
        finishedAt: '2026-10-01T10:00:00.000Z',
      });
      expect(line).toBe(`terminated · ${responseBody}`);
    }
  });

  it('falls back to a generic terminated line when no reason was recorded', () => {
    const line = deliveryStatusLine({
      status: 'FAILED',
      nextRetryAt: null,
      responseBody: null,
      finishedAt: '2026-10-01T10:00:00.000Z',
    });
    expect(line).toBe('terminated · no further retries');
  });

  it('shows the completion time once delivered', () => {
    const line = deliveryStatusLine({
      status: 'DELIVERED',
      nextRetryAt: null,
      responseBody: '{"ok":true}',
      finishedAt: '2026-10-01T10:00:01.000Z',
    });
    expect(line).toContain('delivered');
    expect(line).not.toContain('terminated');
  });
});
