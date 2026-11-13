/**
 * Monitor resource tests.
 *
 * Contract-level tests against fixture data. No live API calls.
 */

import {MonitorResult, MonitorListResult, MonitorEventResult} from '../src/client_state/MonitorResult.js';

const MONITOR_CREATE_FIXTURE: Record<string, unknown> = {
  id: 'monitor_abc1234567',
  object: 'monitor',
  query: 'Watch the Stripe status page for incidents',
  status: 'provisioning',
  tracked: null,
  source_policy: {
    include_urls: ['https://status.stripe.com'],
    exclude_urls: null,
    include_domains: null,
    exclude_domains: null,
  },
  schedule: {
    frequency: 'every hour',
    cron: '0 * * * ? *',
    timezone: 'UTC',
    next_run_at: null,
  },
  notification: {
    events: ['changed', 'first_snapshot'],
    channels: [{type: 'email', target: 'you@example.com', events: null}],
  },
  webhook: null,
  output_schema: null,
  metadata: {},
  agent: {id: 'agent_forward_deployed_0_fda_xyz'},
  last_run: null,
  total_count: null,
  mermaid_diagram: null,
  error_message: null,
  created: 1760327323,
  updated: 1760327323,
};

const MONITOR_GET_FIXTURE: Record<string, unknown> = {
  ...MONITOR_CREATE_FIXTURE,
  status: 'active',
  schedule: {
    frequency: 'every hour',
    cron: '0 * * * ? *',
    timezone: 'UTC',
    next_run_at: '2026-06-19T13:00:00Z',
  },
  last_run: {
    id: 'run_xyz789',
    status: 'completed',
    change_detected: false,
    ran_at: '2026-06-19T12:00:00Z',
  },
  total_count: 5,
};

const MONITOR_LIST_FIXTURE: Record<string, unknown> = {
  monitors: [MONITOR_CREATE_FIXTURE],
  count: 1,
};

const MONITOR_EVENTS_FIXTURE: Record<string, unknown> = {
  data: [
    {
      id: 'run_xyz789',
      run_id: 'run_xyz789',
      created: 1760327323,
      changed: false,
      summary: 'No changes detected.',
      snapshot_url: 'https://olostep-monitor-snapshots.s3.amazonaws.com/snap_abc?X-Amz-Signature=test',
    },
  ],
  has_more: false,
  next_cursor: null,
  total_count: 5,
};

describe('MonitorResult', () => {
  it('parses a provisioning monitor (create response)', () => {
    const r = new MonitorResult(MONITOR_CREATE_FIXTURE);
    expect(r.id).toBe('monitor_abc1234567');
    expect(r.object).toBe('monitor');
    expect(r.status).toBe('provisioning');
    expect(r.query).toBe('Watch the Stripe status page for incidents');
    expect(r.last_run).toBeNull();
    expect(r.total_count).toBeNull();
    expect(r.created).toBe(1760327323);
  });

  it('parses an active monitor with last_run (get response)', () => {
    const r = new MonitorResult(MONITOR_GET_FIXTURE);
    expect(r.status).toBe('active');
    expect(r.last_run).not.toBeNull();
    expect(r.last_run?.change_detected).toBe(false);
    expect(r.last_run?.status).toBe('completed');
    expect(r.total_count).toBe(5);
    expect(r.schedule?.next_run_at).toBe('2026-06-19T13:00:00Z');
  });

  it('exposes metadata as an object', () => {
    const r = new MonitorResult(MONITOR_CREATE_FIXTURE);
    expect(r.metadata).toEqual({});
  });

  it('toString includes id and status', () => {
    const r = new MonitorResult(MONITOR_CREATE_FIXTURE);
    const s = r.toString();
    expect(s).toContain('monitor_abc1234567');
    expect(s).toContain('provisioning');
  });
});

describe('MonitorListResult', () => {
  it('parses list response', () => {
    const r = new MonitorListResult(MONITOR_LIST_FIXTURE);
    expect(r.count).toBe(1);
    expect(r.monitors).toHaveLength(1);
    expect(r.monitors[0].id).toBe('monitor_abc1234567');
  });

  it('is iterable', () => {
    const r = new MonitorListResult(MONITOR_LIST_FIXTURE);
    const ids = [...r].map((m) => m.id);
    expect(ids).toEqual(['monitor_abc1234567']);
  });
});

describe('MonitorEventResult', () => {
  it('parses events response', () => {
    const r = new MonitorEventResult(MONITOR_EVENTS_FIXTURE);
    expect(r.data).toHaveLength(1);
    expect(r.has_more).toBe(false);
    expect(r.next_cursor).toBeNull();
    expect(r.total_count).toBe(5);
  });

  it('is iterable', () => {
    const r = new MonitorEventResult(MONITOR_EVENTS_FIXTURE);
    const ids = [...r].map((e) => e.id);
    expect(ids).toEqual(['run_xyz789']);
  });

  it('event has change detection fields', () => {
    const r = new MonitorEventResult(MONITOR_EVENTS_FIXTURE);
    const event = r.data[0];
    expect(event.changed).toBe(false);
    expect(event.summary).toBe('No changes detected.');
    expect(event.snapshot_url).toContain('s3.amazonaws.com');
  });
});

describe('MonitorResult edge cases', () => {
  it('handles missing optional fields gracefully', () => {
    const r = new MonitorResult({
      id: 'monitor_minimal',
      object: 'monitor',
      query: 'test query',
      status: 'provisioning',
    });
    expect(r.id).toBe('monitor_minimal');
    expect(r.schedule).toBeNull();
    expect(r.notification).toBeNull();
    expect(r.metadata).toEqual({});
    expect(r.last_run).toBeNull();
  });
});
