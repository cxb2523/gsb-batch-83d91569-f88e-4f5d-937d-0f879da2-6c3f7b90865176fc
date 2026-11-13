import Olostep from '../src/index.js';
import {BatchItem} from '../src/types.js';

describe('Olostep SDK - Batch Operations', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  describe('Batch - Shorthand Syntax (camelCase)', () => {
    test('should create batch with camelCase customId', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', customId: 'test-1'},
        {url: 'https://example.org', customId: 'test-2'}
      ]);
      
      expect(batch).toBeDefined();
      expect(batch.id).toMatch(/^batch_/);
      expect(batch.total_urls).toBe(2);
    }, 30000);

    test('should create batch with auto-generated customIds from strings', async () => {
      const batch = await client.batches([
        'https://example.com',
        'https://example.org'
      ]);
      
      expect(batch).toBeDefined();
      expect(batch.id).toMatch(/^batch_/);
      expect(batch.total_urls).toBe(2);
    }, 30000);
  });

  describe('Batch - Shorthand Syntax (snake_case)', () => {
    test('should create batch with snake_case custom_id', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', custom_id: 'test-snake-1'},
        {url: 'https://example.org', custom_id: 'test-snake-2'}
      ] as BatchItem[]);

      expect(batch).toBeDefined();
      expect(batch.id).toMatch(/^batch_/);
      expect(batch.total_urls).toBe(2);
    }, 30000);
  });

  describe('Batch - Explicit Syntax (camelCase)', () => {
    test('should create batch using client.batches.create() with camelCase', async () => {
      const batch = await client.batches.create([
        {url: 'https://example.com', customId: 'explicit-test-1'}
      ]);
      
      expect(batch).toBeDefined();
      expect(batch.id).toMatch(/^batch_/);
    }, 30000);

    test('should get batch info using batch.info()', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', customId: 'info-test'}
      ]);
      
      const info = await batch.info();
      expect(info).toBeDefined();
      expect((info as any).id).toBe(batch.id);
      expect((info as any).status).toBeDefined();
    }, 30000);

    test('should use client.batches.info() to get batch info by ID', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', customId: 'info-by-id-test'}
      ]);
      
      const info = await client.batches.info(batch.id);
      expect(info).toBeDefined();
      expect((info as any).id).toBe(batch.id);
    }, 30000);
  });

  describe('Batch - Explicit Syntax (snake_case)', () => {
    test('should create batch using client.batches.create() with snake_case', async () => {
      const batch = await client.batches.create([
        {url: 'https://example.com', custom_id: 'explicit-snake-1'}
      ] as BatchItem[]);

      expect(batch).toBeDefined();
      expect(batch.id).toMatch(/^batch_/);
    }, 30000);

    test('should get batch info using batch.info() with snake_case item', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', custom_id: 'info-snake-test'}
      ] as BatchItem[]);

      const info = await batch.info();
      expect(info).toBeDefined();
      expect((info as any).id).toBe(batch.id);
      expect((info as any).status).toBeDefined();
    }, 30000);

    test('should use client.batches.info() with snake_case item', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', custom_id: 'info-by-id-snake'}
      ] as BatchItem[]);

      const info = await client.batches.info(batch.id);
      expect(info).toBeDefined();
      expect((info as any).id).toBe(batch.id);
    }, 30000);
  });

  describe('Batch - waitTillDone (camelCase)', () => {
    test('should wait for batch completion with camelCase options', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', customId: 'wait-test'}
      ]);
      
      await expect(
        batch.waitTillDone({checkEveryNSecs: 3, timeoutSeconds: 120})
      ).resolves.not.toThrow();
      
      const info = await batch.info();
      expect((info as any).status).toBe('completed');
    }, 150000);

    test('should timeout if batch takes too long (camelCase)', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', customId: 'timeout-test'}
      ]);

      // Force a non-terminal status so the timeout path is deterministic
      // rather than racing how fast the live batch actually finishes.
      (batch as any).info = async () => ({status: 'in_progress'});

      await expect(
        batch.waitTillDone({checkEveryNSecs: 1, timeoutSeconds: 1})
      ).rejects.toThrow('timed out');
    }, 30000);
  });

  describe('Batch - waitTillDone (snake_case)', () => {
    test('should wait for batch completion with snake_case options', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', custom_id: 'wait-snake-test'}
      ] as BatchItem[]);

      await expect(
        batch.waitTillDone({check_every_n_secs: 3, timeout_seconds: 120})
      ).resolves.not.toThrow();

      const info = await batch.info();
      expect((info as any).status).toBe('completed');
    }, 150000);

    test('should timeout if batch takes too long (snake_case)', async () => {
      const batch = await client.batches([
        {url: 'https://example.com', custom_id: 'timeout-snake-test'}
      ] as BatchItem[]);

      // Force a non-terminal status so the timeout path is deterministic
      // rather than racing how fast the live batch actually finishes.
      (batch as any).info = async () => ({status: 'in_progress'});

      await expect(
        batch.waitTillDone({check_every_n_secs: 1, timeout_seconds: 1})
      ).rejects.toThrow('timed out');
    }, 30000);
  });
});
