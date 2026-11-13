import Olostep from '../src/index.js';
import {logJSON} from './helpers.js';

async function main() {
  console.log('=== Batch Processing Examples ===\n');

  const client = new Olostep();

  // Syntax 1: Direct shorthand call
  console.log('1. Using client.batches() - shorthand syntax\n');
  const batch1 = await client.batches([
    { url: 'https://example.com', customId: 'example-com' },
    { url: 'https://example.org', customId: 'example-org' }
  ]);
  console.log(`Batch created: ${batch1.id} (${batch1.total_urls} URLs)`);

  // Syntax 2: Explicit method call (also works)
  console.log('\n2. Using client.batches.create() - explicit syntax\n');
  const batch2 = await client.batches.create([
    { url: 'https://example.net', customId: 'example-net' }
  ]);
  console.log(`Batch created: ${batch2.id}`);

  logJSON('Batch handle', {id: batch1.id, total_urls: batch1.total_urls});

  const info = await batch1.info();
  logJSON('Batch info (initial)', info);

  // Wait for batch to complete
  console.log('\n3. Using batch.waitTillDone() to wait for completion\n');
  console.log('Waiting for batch to complete...');
  await batch1.waitTillDone({checkEveryNSecs: 5, timeoutSeconds: 120});
  console.log('Batch completed!');

  // Get final info
  const finalInfo = await batch1.info();
  logJSON('Batch info (final)', finalInfo);

  console.log('\n✅ All batch methods work!\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

