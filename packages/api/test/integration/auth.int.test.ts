import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import type { FastifyInstance } from 'fastify';
import {
  createTestApp,
  runMigrations,
  createTestUser,
  cleanDatabase,
  ensureS3Bucket,
} from './setup.js';

describe('Auth (integration)', () => {
  let app: FastifyInstance;

  beforeAll(async () => {
    await ensureS3Bucket();
    app = await createTestApp();
    await runMigrations();
  });

  afterEach(async () => {
    await cleanDatabase();
  });

  afterAll(async () => {
    await app.close();
  });

  it('logs in with valid credentials and gets a token', async () => {
    await createTestUser('login@test.local', 'mypassword');

    const login = await app.inject({
      method: 'POST',
      url: '/v2/auth/login',
      payload: { email: 'login@test.local', password: 'mypassword' },
    });
    expect(login.statusCode).toBe(200);
    expect(login.json().data.token).toBeDefined();
  });

  it('rejects invalid credentials', async () => {
    await createTestUser('real@test.local', 'correctpassword');

    const login = await app.inject({
      method: 'POST',
      url: '/v2/auth/login',
      payload: { email: 'real@test.local', password: 'wrongpassword' },
    });
    expect(login.statusCode).toBe(401);
  });

  it('rejects requests without auth token', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/v2/acts',
    });
    expect(res.statusCode).toBe(401);
  });

  it('creates and uses an API key', async () => {
    const user = await createTestUser('apikey@test.local', 'password123');

    // Create API key
    const keyRes = await app.inject({
      method: 'POST',
      url: '/v2/auth/api-keys',
      headers: { authorization: `Bearer ${user.token}` },
      payload: { name: 'test-key' },
    });
    expect(keyRes.statusCode).toBe(201);
    const apiKey = keyRes.json().data.key;
    expect(apiKey).toMatch(/^cp_/);

    // Use API key to list actors
    const actors = await app.inject({
      method: 'GET',
      url: '/v2/acts',
      headers: { authorization: `Bearer ${apiKey}` },
    });
    expect(actors.statusCode).toBe(200);
  });
});
