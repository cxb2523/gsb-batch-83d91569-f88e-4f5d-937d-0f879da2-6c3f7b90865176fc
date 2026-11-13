/**
 * Docs command tests for docs/features/answers.mdx Node SDK snippets.
 *
 * These tests intentionally mirror the Node SDK code blocks from:
 * docs/features/answers.mdx
 *
 * Run: npx jest tests/docs_commands/answers.docs.test.ts --verbose
 *
 * Live API tests need OLOSTEP_API_KEY; without it they throw in beforeAll.
 */

import Olostep from '../../src/index.js';

describe('Answers Feature Docs Commands', () => {
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

  test('basic answer with json format command', async () => {
    // Mirrors docs snippet in "## Usage" (Node SDK).
    const answer = await client.answers.create({
      task: 'What is the latest book by J.K. Rowling?',
      jsonFormat: { book_title: '', author: '', release_date: '' },
    });

    expect(answer.json_content).toBeDefined();
    expect(answer.sources).toBeDefined();
  }, 60000);

  test('flexible json parameter command', async () => {
    // Mirrors docs snippet in "### Flexible `json` parameter" (Node SDK).
    const answer = await client.answers.create({
      task: 'how much did Olostep raise?',
      jsonFormat: { amount: '' },
    });

    expect(answer.json_content).toBeDefined();
  }, 60000);
});
