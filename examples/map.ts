import {createClient, logJSON} from './helpers.js';

async function main() {
  const client = createClient();

  const map = await client.maps.create({
    url: 'https://example.com',
    topN: 50
  });

  logJSON('Map result', {
    id: map.id,
    urls_count: (map as any).urls_count
  });

  // Demonstrate URL streaming
  console.log('\n=== Streaming URLs ===');
  let count = 0;
  for await (const url of map.urls()) {
    console.log(`[${++count}] ${url}`);
  }
  console.log(`\nTotal URLs streamed: ${count}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

