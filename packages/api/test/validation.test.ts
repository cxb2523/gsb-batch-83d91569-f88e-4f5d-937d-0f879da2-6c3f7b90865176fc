import { describe, it, expect, beforeAll, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';
import Fastify from 'fastify';
import { ZodError } from 'zod';
import { actorsRoutes } from '../src/routes/actors.js';

// Mock auth
vi.mock('../src/auth/middleware.js', () => ({
  authenticate: async (request: { user?: { id: string; email: string; role: string } }) => {
    request.user = { id: 'test-user-id', email: 'test@example.com', role: 'user' };
  },
}));

// Mock DB
const mockQuery = vi.fn();
vi.mock('../src/db/index.js', () => ({
  query: (...args: unknown[]) => mockQuery(...args),
}));

describe('Input Validation', () => {
  let app: FastifyInstance;

  beforeAll(async () => {
    app = Fastify();

    // Add the error handler we want to test
    app.setErrorHandler((error: any, request, reply) => {
      if (error instanceof ZodError) {
        return reply.status(400).send({
          error: {
            type: 'validation_error',
            message: 'Validation failed',
            details: error.errors,
          },
        });
      }
      reply.status(500).send({ error });
    });

    await app.register(actorsRoutes);
    await app.ready();
  });

  it('should reject invalid actor creation (invalid name)', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/acts',
      payload: {
        name: 'Invalid Name with Spaces', // Regex only allows alphanumeric and dashes
      },
    });

    expect(response.statusCode).toBe(400);
    const body = response.json();
    expect(body.error.type).toBe('validation_error');
    expect(body.error.details[0].path).toContain('name');
  });

  it('should reject actor creation with too long description', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/acts',
      payload: {
        name: 'valid-name',
        description: 'a'.repeat(5001), // Max 5000
      },
    });

    expect(response.statusCode).toBe(400);
  });

  it('should accept valid actor creation', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [] }); // Check existing
    mockQuery.mockResolvedValueOnce({ rows: [{ id: '1', name: 'valid-name' }] }); // Insert

    const response = await app.inject({
      method: 'POST',
      url: '/acts',
      payload: {
        name: 'valid-name',
        title: 'Valid Title',
      },
    });

    expect(response.statusCode).toBe(201);
  });
});
