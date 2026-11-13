import {Format} from '../src/types.js';
import Olostep from '../src/index.js';
import {logJSON} from './helpers.js';

async function main() {
  console.log('=== Search Examples ===\n');

  const client = new Olostep();

  // 1. Plain string query
  console.log('1. Using client.searches() with a plain string query\n');
  const search = await client.searches('Best Answer Engine Optimization startups');
  logJSON('Search result', {
    id: search.id,
    query: search.query,
    links: search.links.length,
    credits_consumed: search.credits_consumed
  });

  // 2. Limit + domain filtering
  console.log('\n2. Limit + include/exclude domains\n');
  const filtered = await client.searches.create({
    query: 'OpenAI Sora shutdown analysis',
    limit: 5,
    includeDomains: ['bbc.com', 'nytimes.com', 'wsj.com'],
    excludeDomains: ['pinterest.com']
  });
  for (const link of filtered.links) {
    console.log(`- ${link.url}`);
  }

  // 3. Search + scrape in one round-trip
  console.log('\n3. Search + scrapeOptions to embed page content\n');
  const enriched = await client.searches.create({
    query: "What's going on with OpenAI's Sora shutting down?",
    limit: 5,
    scrapeOptions: {
      formats: [Format.MARKDOWN],
      timeout: 25
    }
  });
  for (const link of enriched.links) {
    const chars = (link.markdown_content || '').length;
    console.log(`- ${link.url} — ${chars} chars`);
  }

  // 4. Retrieve a previously created search
  console.log('\n4. Using client.searches.get() to fetch a past search\n');
  const fetched = await client.searches.get(search.id);
  console.log(`Retrieved search: ${fetched.id} (${fetched.links.length} links)`);

  console.log('\nDone.\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
