import {Format} from '../src/types.js';
import Olostep from '../src/index.js';
import {logJSON} from './helpers.js';

async function main() {
  console.log('=== Scrape Examples ===\n');

  // Create client (reads from OLOSTEP_API_KEY env variable)
  // You can also pass API key directly: new Olostep({ apiKey: 'olostep_xxx...' })
  const client = new Olostep();

  // Syntax 1: Direct shorthand call
  console.log('1. Using client.scrapes.create() - shorthand syntax\n');
  const scrape = await client.scrapes.create({
    url: 'https://example.com',
    formats: [Format.HTML, Format.MARKDOWN],
    waitBeforeScraping: 1000
  });

  logJSON('Scrape result', {
    id: scrape.id,
    htmlBytes: scrape.html_content?.length ?? 0,
    markdownBytes: scrape.markdown_content?.length ?? 0,
    retrieve_id: scrape.retrieve_id
  });

  // Syntax 2: Explicit method call (also works)
  console.log('\n2. Using client.scrapes.create() - explicit syntax\n');
  const scrape2 = await client.scrapes.create('https://example.com');
  console.log(`Scrape ID: ${scrape2.id}`);

  // Get scrape by ID
  console.log('\n3. Using client.scrapes.get() to retrieve by ID\n');
  const fetched = await client.scrapes.get(scrape.id as string);
  console.log(`Retrieved scrape: ${fetched.id}`);

  if (scrape.retrieve_id) {
    console.log('\n4. Using client.retrieve() to get content\n');
    const retrieved = await client.retrieve(scrape.retrieve_id, Format.HTML);
    logJSON('Retrieved content', {
      htmlBytes: retrieved.html_content?.length ?? 0,
      availableFields: Object.keys(retrieved).filter((key) => key.endsWith('_content'))
    });
  } else {
    console.log('\nRetrieve ID not available for this scrape.');
  }

  console.log('\n✅ All scrape methods work!\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});