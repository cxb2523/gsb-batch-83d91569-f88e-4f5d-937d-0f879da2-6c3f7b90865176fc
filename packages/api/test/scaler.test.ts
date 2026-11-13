/**
 * Scaler Routes Tests
 *
 * Verifies that GET /v2/scaler/status is gated by requireAdmin:
 *  - unauthenticated -> 401
 *  - non-admin user  -> 403
 *  - admin           -> 200 with status payload
 */

import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import Fastify from 'fastify';

type Role = 'admin' | 'user';
type MockUser = { id: string; email: string; role: Role } | null;

// vi.hoisted so the mock factory's closure references the same `state`
// the tests mutate (vi.mock is hoisted above module-level `let`).
const { state } = vi.hoisted(() => ({
  state: { currentUser: null as MockUser },
}));

// Mock `requireAdmin` directly: the real implementation calls
// `authenticate` via an internal reference (not the export), so
// mocking only `authenticate` would have no effect on requireAdmin.
// Coverage for requireAdmin's own logic belongs in auth.test.ts.
vi.mock('../src/auth/middleware.js', () => ({
  requireAdmin: async (request: FastifyRequest, reply: FastifyReply) => {
    if (!state.currentUser) {
      reply.status(401).send({ error: { message: 'Authentication required' } });
      return;
    }
    if (state.currentUser.role !== 'admin') {
      reply.status(403).send({ error: { message: 'Admin access required' } });
      return;
    }
    request.user = { ...state.currentUser };
  },
}));

vi.mock('../src/scaler/index.js', () => ({
  getScalerStatus: vi.fn().mockResolvedValue({
    enabled: true,
    provider: 'digitalocean',
    runners: [
      {
        id: 'r1',
        ip: '10.0.0.1',
        status: 'active',
        activeRuns: 0,
        createdAt: '2026-04-01T00:00:00Z',
      },
    ],
    heartbeats: [],
    queue: { depth: 0 },
    config: { min: 1, max: 10, runsPerRunner: 3 },
  }),
}));

import { scalerRoutes } from '../src/routes/scaler.js';

describe('Scaler Routes', () => {
  let app: FastifyInstance;

  beforeAll(async () => {
    app = Fastify();
    await app.register(scalerRoutes, { prefix: '/v2' });
    await app.ready();
  });

  afterAll(async () => {
    await app.close();
  });

  it('rejects unauthenticated requests with 401', async () => {
    state.currentUser = null;
    const res = await app.inject({ method: 'GET', url: '/v2/scaler/status' });
    expect(res.statusCode).toBe(401);
  });

  it('rejects non-admin users with 403', async () => {
    state.currentUser = { id: 'u1', email: 'u1@example.com', role: 'user' };
    const res = await app.inject({ method: 'GET', url: '/v2/scaler/status' });
    expect(res.statusCode).toBe(403);
  });

  it('returns scaler status for admins', async () => {
    state.currentUser = { id: 'a1', email: 'admin@example.com', role: 'admin' };
    const res = await app.inject({ method: 'GET', url: '/v2/scaler/status' });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload) as {
      data: { enabled: boolean; runners: unknown[] };
    };
    expect(body.data.enabled).toBe(true);
    expect(body.data.runners).toHaveLength(1);
  });
});
