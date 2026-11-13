/**
 * Docs command tests for docs/features/batches.mdx Node SDK snippets.
 *
 * These tests intentionally mirror the Node SDK code blocks from:
 * docs/features/batches.mdx
 *
 * Run: npx jest tests/docs_commands/batches.docs.test.ts --verbose
 *
 * Live API tests need OLOSTEP_API_KEY; without it they throw in beforeAll.
 */

import Olostep from '../../src/index.js';
import {Format} from '../../src/types.js';

describe('Batches Feature Docs Commands', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  test('installation import command', () => {
    expect(Olostep).toBeDefined();
  });

  test('start batch command', async () => {
    // Mirrors docs snippet in "## Start a batch" (Node SDK).
    const batch = await client.batches.create([
      { url: 'https://www.google.com/search?q=stripe&gl=us&hl=en', customId: 'item-1' },
      { url: 'https://www.google.com/search?q=paddle&gl=us&hl=en', customId: 'item-2' },
    ], {
      parser: '@olostep/google-search',
    });

    expect(batch.id).toBeDefined();
    expect(batch.total_urls).toBe(2);
  }, 30000);

  test('batch info command', async () => {
    // Mirrors docs snippet in "## Check batch status" (Node SDK).
    const batch = await client.batches.create([
      { url: 'https://www.google.com/search?q=stripe&gl=us&hl=en', customId: 'item-1' },
    ], {
      parser: '@olostep/google-search',
    });

    const info = await batch.info();
    expect(info).toBeDefined();
    expect((info as any).status).toBeDefined();
  }, 30000);

  test('batch items and retrieve command', async () => {
    // Mirrors docs snippet in "## Retrieve content" (Node SDK).
    const batch = await client.batches.create([
      { url: 'https://www.google.com/search?q=stripe&gl=us&hl=en', customId: 'item-1' },
      { url: 'https://www.google.com/search?q=paddle&gl=us&hl=en', customId: 'item-2' },
    ], {
      parser: '@olostep/google-search',
    });

    for await (const item of batch.items()) {
      const content = await item.retrieve([Format.JSON]);
      expect(item.url).toBeDefined();
      expect(item.custom_id).toBeDefined();
      expect((content as any).json_content).toBeDefined();
      break; // Only test the first item
    }
  }, 300000);
});
