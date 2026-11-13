import {Format} from '../src/types.js';

import {createClient, logJSON} from './helpers.js';

async function main() {
  const retrieveId = process.argv[2];

  if (!retrieveId) {
    throw new Error('Usage: node retrieve.js <retrieve_id>');
  }

  const client = createClient();

  const result = await client.retrieve(retrieveId, [Format.HTML, Format.JSON]);
  logJSON('Retrieve result', result);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

