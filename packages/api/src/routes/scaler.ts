/**
 * Scaler routes - operational endpoints for the auto-scaler.
 *
 * Always admin-only. The response includes runner IPs, cloud provider,
 * queue depth, and scaler config — there is no use case where this should
 * be public, so unlike /metrics there is no METRICS_PUBLIC-style escape
 * hatch.
 */

import type { FastifyPluginAsync } from 'fastify';
import { requireAdmin } from '../auth/middleware.js';
import { getScalerStatus } from '../scaler/index.js';

export const scalerRoutes: FastifyPluginAsync = async (fastify) => {
  fastify.addHook('preHandler', requireAdmin);

  fastify.get('/scaler/status', async () => {
    return { data: await getScalerStatus() };
  });
};
