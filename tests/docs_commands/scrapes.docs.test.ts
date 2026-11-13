/**
 * Docs command tests for docs/features/scrapes.mdx Node SDK snippets.
 *
 * These tests intentionally mirror the Node SDK code blocks from:
 * docs/features/scrapes.mdx
 *
 * Run: npx jest tests/docs_commands/scrapes.docs.test.ts --verbose
 *
 * Live API tests need OLOSTEP_API_KEY; without it they throw in beforeAll.
 */

import Olostep from '../../src/index.js';

describe('Scrapes Feature Docs Commands', () => {
  let client: Olostep;

  beforeAll(() => {
    if (!process.env.OLOSTEP_API_KEY) {
      throw new Error('OLOSTEP_API_KEY environment variable is required for tests');
    }
    client = new Olostep();
  });

  test('installation import command', () => {
    // Equivalent to docs "Installation" Node SDK snippet.
    // npm install olostep
    // import Olostep from 'olostep'
    expect(Olostep).toBeDefined();
  });

  test('basic scrape usage command', async () => {
    // Mirrors docs snippet in "### Usage" (Node SDK).
    const result = await client.scrapes.create({
      url: 'https://en.wikipedia.org/wiki/Alexander_the_Great',
      formats: ['markdown', 'html'],
    });

    expect(result.markdown_content).toBeDefined();
    expect(result.html_content).toBeDefined();
  }, 30000);

  test('structured extraction parser command', async () => {
    // Mirrors docs snippet in "Using a Parser" (Node SDK).
    const result = await client.scrapes.create({
      url: 'https://www.google.com/search?q=alexander+the+great&gl=us&hl=en',
      formats: ['json'],
      parser: '@olostep/google-search',
    });

    expect(result.json_content).toBeDefined();
  }, 30000);

  test('llm extraction schema command', async () => {
    // Mirrors docs snippet in "Using LLM extraction" (Node SDK).
    const result = await client.scrapes.create({
      url: 'https://www.berklee.edu/events/stefano-marchese-friends',
      formats: ['markdown', 'json'],
      llmExtract: {
        // The API requires a JSON Schema object at the top level.
        schema: {
          type: 'object',
          properties: {
            event: {
              type: 'object',
              properties: {
                title: { type: 'string' },
                date: { type: 'string' },
                description: { type: 'string' },
                venue: { type: 'string' },
                address: { type: 'string' },
                start_time: { type: 'string' },
              },
            },
          },
        },
      },
    });

    expect(result.json_content).toBeDefined();
  }, 60000);

  test('actions interaction flow command', async () => {
    // Mirrors docs snippet in "Interacting with the page with Actions" (Node SDK).
    const result = await client.scrapes.create({
      url: 'https://example.com/login',
      formats: ['markdown'],
      actions: [
        { type: 'fill_input', selector: 'input[type=email]', value: 'john@example.com' },
        { type: 'wait', milliseconds: 500 },
        { type: 'fill_input', selector: 'input[type=password]', value: 'secret' },
        { type: 'click', selector: 'button[type="submit"]' },
        { type: 'wait', milliseconds: 1500 },
      ],
    });

    expect(result.markdown_content).toBeDefined();
  }, 60000);
});
