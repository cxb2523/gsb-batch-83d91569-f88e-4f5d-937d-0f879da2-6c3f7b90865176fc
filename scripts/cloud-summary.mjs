import { readFile, appendFile } from 'node:fs/promises';
let result;
try { result = JSON.parse(await readFile('.local/cloud-update/publish-result.json')); } catch {}
const text = result ? '## Test data published\n\n- Archive: `' + result.archive_id + '`\n- Daily flows through: ' + result.flow_through + '\n- Test site: ' + result.site + '\n- Verified at: ' + result.verified_at + '\n' : '## Test update did not complete\n\nSee the failed step for collection, upload or rollback status. No formal domain changes were made.\n';
if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, text);
console.log(result ? 'Test publish verified; cloud snapshot archived.' : 'No successful test publish recorded.');
