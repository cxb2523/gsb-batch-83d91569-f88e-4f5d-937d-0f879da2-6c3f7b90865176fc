/**
 * Docs command tests for docs/features/maps.mdx Node SDK snippets.
 *
 * These tests intentionally mirror the Node SDK code blocks from:
 * docs/features/maps.mdx
 *
 * Run: npx jest tests/docs_commands/maps.docs.test.ts --verbose
 *
 * Live API tests need OLOSTEP_API_KEY; without it they throw in beforeAll.
 */

import Olostep from '../../src/index.js';

describe('Maps Feature Docs Commands', () => {
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

  test('basic map usage command', async () => {
    // Mirrors docs snippet in "## Usage" (Node SDK).
    const map = await client.maps.create({ url: 'https://docs.olostep.com' });

    const urls: string[] = [];
    for await (const url of map.urls()) {
      urls.push(url);
      if (urls.length >= 10) break;
    }

    expect(urls.length).toBeGreaterThan(0);
  }, 120000);

  test('map with include urls command', async () => {
    // Mirrors docs snippet in "### Example" (Node SDK).
    const map = await client.maps.create({
      url: 'https://www.brex.com/',
      includeUrls: ['/product', '/product/**'],
      topN: 100000,
    });

    const urls: string[] = [];
    for await (const url of map.urls()) {
      urls.push(url);
      if (urls.length >= 10) break;
    }

    expect(urls.length).toBeGreaterThanOrEqual(0);
  }, 120000);
});
