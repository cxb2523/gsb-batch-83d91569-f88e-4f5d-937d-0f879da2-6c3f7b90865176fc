/**
 * Cleanup old runs and associated data.
 *
 * Usage:
 *   npx tsx scripts/cleanup-old-data.ts --retention-days 90 --dry-run
 *   npx tsx scripts/cleanup-old-data.ts --retention-days 90
 */

import pg from 'pg';
import { S3Client, DeleteObjectsCommand, ListObjectsV2Command } from '@aws-sdk/client-s3';

const { Pool } = pg;

// Parse CLI args
const args = process.argv.slice(2);
function getArg(name: string, defaultValue: string): string {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : defaultValue;
}
const dryRun = args.includes('--dry-run');
const retentionDays = parseInt(getArg('retention-days', '90'), 10);
const webhookRetentionDays = parseInt(getArg('webhook-retention-days', '30'), 10);
const batchSize = parseInt(getArg('batch-size', '100'), 10);

// Initialize connections from env
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const s3 = new S3Client({
  endpoint: process.env.S3_ENDPOINT,
  region: process.env.S3_REGION ?? 'us-east-1',
  credentials: {
    accessKeyId: process.env.S3_ACCESS_KEY ?? '',
    secretAccessKey: process.env.S3_SECRET_KEY ?? '',
  },
  forcePathStyle: true,
});
const bucket = process.env.S3_BUCKET ?? 'crawlee-cloud';

const stats = {
  runs: 0,
  datasets: 0,
  kvStores: 0,
  queues: 0,
  requests: 0,
  s3Objects: 0,
  webhookDeliveries: 0,
};

async function deleteS3Prefix(prefix: string): Promise<number> {
  let deleted = 0;
  let continuationToken: string | undefined;

  do {
    const list = await s3.send(
      new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: prefix,
        ContinuationToken: continuationToken,
      })
    );

    const objects = list.Contents?.map((o) => ({ Key: o.Key }));
    if (objects && objects.length > 0) {
      if (!dryRun) {
        await s3.send(
          new DeleteObjectsCommand({
            Bucket: bucket,
            Delete: { Objects: objects },
          })
        );
      }
      deleted += objects.length;
    }
    continuationToken = list.NextContinuationToken;
  } while (continuationToken);

  return deleted;
}

async function cleanupRuns(): Promise<void> {
  console.log(`\nCleaning up runs older than ${String(retentionDays)} days...`);

  let totalProcessed = 0;
  while (true) {
    const result = await pool.query<{
      id: string;
      default_dataset_id: string | null;
      default_key_value_store_id: string | null;
      default_request_queue_id: string | null;
    }>(
      `SELECT id, default_dataset_id, default_key_value_store_id, default_request_queue_id
       FROM runs
       WHERE status IN ('SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED')
         AND finished_at < NOW() - INTERVAL '1 day' * $1
       LIMIT $2`,
      [retentionDays, batchSize]
    );

    if (result.rows.length === 0) break;

    for (const run of result.rows) {
      if (run.default_dataset_id) {
        stats.s3Objects += await deleteS3Prefix(`datasets/${run.default_dataset_id}/`);
        if (!dryRun)
          await pool.query('DELETE FROM datasets WHERE id = $1', [run.default_dataset_id]);
        stats.datasets++;
      }

      if (run.default_key_value_store_id) {
        stats.s3Objects += await deleteS3Prefix(
          `key-value-stores/${run.default_key_value_store_id}/`
        );
        if (!dryRun)
          await pool.query('DELETE FROM key_value_stores WHERE id = $1', [
            run.default_key_value_store_id,
          ]);
        stats.kvStores++;
      }

      if (run.default_request_queue_id) {
        const reqResult = await pool.query<{ count: string }>(
          'SELECT COUNT(*) as count FROM requests WHERE queue_id = $1',
          [run.default_request_queue_id]
        );
        stats.requests += parseInt(String(reqResult.rows[0]!.count), 10);
        if (!dryRun) {
          await pool.query('DELETE FROM requests WHERE queue_id = $1', [
            run.default_request_queue_id,
          ]);
          await pool.query('DELETE FROM request_queues WHERE id = $1', [
            run.default_request_queue_id,
          ]);
        }
        stats.queues++;
      }

      if (!dryRun) await pool.query('DELETE FROM runs WHERE id = $1', [run.id]);
      stats.runs++;
    }

    totalProcessed += result.rows.length;
    console.log(`  Processed ${String(totalProcessed)} runs...`);
  }
}

async function cleanupWebhookDeliveries(): Promise<void> {
  console.log(
    `\nCleaning up webhook deliveries older than ${String(webhookRetentionDays)} days...`
  );

  if (dryRun) {
    const result = await pool.query<{ count: string }>(
      `SELECT COUNT(*) as count FROM webhook_deliveries
       WHERE created_at < NOW() - INTERVAL '1 day' * $1
         AND status IN ('DELIVERED', 'FAILED')`,
      [webhookRetentionDays]
    );
    stats.webhookDeliveries = parseInt(String(result.rows[0]!.count), 10);
  } else {
    const result = await pool.query(
      `DELETE FROM webhook_deliveries
       WHERE created_at < NOW() - INTERVAL '1 day' * $1
         AND status IN ('DELIVERED', 'FAILED')`,
      [webhookRetentionDays]
    );
    stats.webhookDeliveries = result.rowCount ?? 0;
  }
}

async function main(): Promise<void> {
  console.log('Crawlee Cloud Data Cleanup');
  console.log('='.repeat(40));
  if (dryRun) console.log('DRY RUN — no data will be deleted');
  console.log(`Run retention: ${String(retentionDays)} days`);
  console.log(`Webhook delivery retention: ${String(webhookRetentionDays)} days`);
  console.log(`Batch size: ${String(batchSize)}`);

  await cleanupRuns();
  await cleanupWebhookDeliveries();

  console.log('\n' + '='.repeat(40));
  console.log('Summary:');
  console.log(`  Runs: ${String(stats.runs)}`);
  console.log(`  Datasets: ${String(stats.datasets)}`);
  console.log(`  KV Stores: ${String(stats.kvStores)}`);
  console.log(`  Request Queues: ${String(stats.queues)} (${String(stats.requests)} requests)`);
  console.log(`  S3 Objects: ${String(stats.s3Objects)}`);
  console.log(`  Webhook Deliveries: ${String(stats.webhookDeliveries)}`);

  await pool.end();
  process.exit(0);
}

main().catch((err: unknown) => {
  console.error('Cleanup failed:', err);
  process.exit(1);
});
