import Olostep from '../src/index.js';
import {logJSON} from './helpers.js';

async function main() {
  console.log('=== Crawl Examples ===\n');

  const client = new Olostep();

  // Syntax 1: Direct shorthand call (also works: client.crawls.create())
  console.log('1. Using client.crawls() - shorthand syntax\n');
  const crawl = await client.crawls.create({
    url: 'https://example.com',
    maxPages: 5,
    maxDepth: 1
  });

  logJSON('Crawl handle', {id: crawl.id});

  // Wait a bit for crawl to start processing
  console.log('\n2. Waiting for crawl to start processing...\n');
  await new Promise(resolve => setTimeout(resolve, 3000));

  const info = await crawl.info();
  logJSON('Crawl info (initial)', info);

  // Wait for crawl to complete (optional - can take time)
  console.log('\n3. Using crawl.waitTillDone() to wait for completion\n');
  console.log('Waiting for crawl to complete (max 2 minutes)...');
  try {
    await crawl.waitTillDone({checkEveryNSecs: 10, timeoutSeconds: 120});
    console.log('Crawl completed!');

    const finalInfo = await crawl.info();
    logJSON('Crawl info (final)', finalInfo);
  } catch (err) {
    console.log('Note: Crawl may still be in progress (timeout or incomplete)');
    const currentInfo = await crawl.info();
    logJSON('Crawl info (current)', currentInfo);
  }

  console.log('\n✅ Crawl methods work!\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

