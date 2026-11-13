/**
 * Docs command tests for docs/features/crawls.mdx Node SDK snippets.
 *
 * These tests intentionally mirror the Node SDK code blocks from:
 * docs/features/crawls.mdx
 *
 * Run: npx jest tests/docs_commands/crawls.docs.test.ts --verbose
 *
 * Live API tests need OLOSTEP_API_KEY; without it they throw in beforeAll.
 */

import Olostep from '../../src/index.js';
import {Format} from '../../src/types.js';

describe('Crawls Feature Docs Commands', () => {
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

  test('start crawl command', async () => {
    // Mirrors docs snippet in "## Start a crawl" (Node SDK).
    const crawl = await client.crawls.create({
      url: 'https://olostep.com',
      maxPages: 5,
      includeUrls: ['/**'],
      excludeUrls: ['/collections/**'],
      includeExternal: false,
    });

    expect(crawl.id).toBeDefined();
    expect(crawl.status).toBeDefined();
  }, 30000);

  test('check crawl status command', async () => {
    // Mirrors docs snippet in "## Check crawl status" (Node SDK).
    const crawl = await client.crawls.create({
      url: 'https://olostep.com',
      maxPages: 5,
      includeUrls: ['/**'],
    });

    const info = await crawl.info();
    expect(info).toBeDefined();
    expect((info as any).status).toBeDefined();
  }, 30000);

  test('list pages command', async () => {
    // Mirrors docs snippet in "## List pages" (Node SDK).
    const crawl = await client.crawls.create({
      url: 'https://olostep.com',
      maxPages: 5,
      includeUrls: ['/**'],
    });

    const pages: any[] = [];
    for await (const page of crawl.pages()) {
      pages.push(page);
      expect(page.url).toBeDefined();
      expect(page.retrieve_id).toBeDefined();
      if (pages.length >= 3) break;
    }

    expect(pages.length).toBeGreaterThan(0);
  }, 300000);

  test('retrieve content command', async () => {
    // Mirrors docs snippet in "## Retrieve content" (Node SDK).
    const crawl = await client.crawls.create({
      url: 'https://olostep.com',
      maxPages: 5,
      includeUrls: ['/**'],
    });

    for await (const page of crawl.pages()) {
      const content = await client.retrieve.get(page.retrieve_id!, [Format.MARKDOWN]);
      expect(content).toBeDefined();
      expect((content as any).markdown_content).toBeDefined();
      break; // Only test the first page
    }
  }, 300000);
});
