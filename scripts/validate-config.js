/**
 * Configuration Security Validator
 *
 * Standalone script that checks environment variables for insecure defaults.
 * Shares constant definitions with packages/api/src/config-validator.ts
 * via packages/api/src/security-constants.json.
 */

import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const constants = JSON.parse(
  readFileSync(join(__dirname, '..', 'packages', 'api', 'src', 'security-constants.json'), 'utf-8')
);

const WEAK_SECRETS = constants.weakSecrets;
const INSECURE_DB_PASSWORDS = constants.insecureDbPasswords;
const INSECURE_S3_CREDENTIALS = constants.insecureS3Credentials;

console.log('--- Crawlee Cloud Security Validation ---');

let hasErrors = false;
let hasWarnings = false;

function error(msg) {
  console.error(`  ERROR: ${msg}`);
  hasErrors = true;
}

function warn(msg) {
  console.warn(`  WARNING: ${msg}`);
  hasWarnings = true;
}

// Check API_SECRET (the actual env var used by the application)
const apiSecret = process.env.API_SECRET;
if (!apiSecret) {
  warn('API_SECRET is not set. Application will use insecure development default.');
} else if (WEAK_SECRETS.some(weak => apiSecret.toLowerCase() === weak.toLowerCase())) {
  error('API_SECRET is a known weak/default value. Set a strong, unique secret.');
} else if (apiSecret.length < 32) {
  warn(`API_SECRET is only ${apiSecret.length} chars. Minimum 32 recommended.`);
} else {
  console.log('  OK: API_SECRET');
}

// Check DATABASE_URL for insecure passwords
const dbUrl = process.env.DATABASE_URL;
if (!dbUrl) {
  warn('DATABASE_URL is not set. Application will use insecure development default.');
} else {
  const dbInsecure = INSECURE_DB_PASSWORDS.find(pw => dbUrl.includes(`:${pw}@`));
  if (dbInsecure) {
    error('DATABASE_URL contains a known insecure default password');
  } else {
    console.log('  OK: DATABASE_URL');
  }
}

// Check S3 credentials
const s3Access = process.env.S3_ACCESS_KEY;
const s3Secret = process.env.S3_SECRET_KEY;
if (!s3Access || !s3Secret) {
  warn('S3 credentials not set. Application will use insecure development defaults.');
} else {
  const s3Insecure = INSECURE_S3_CREDENTIALS.find(c => s3Access === c || s3Secret === c);
  if (s3Insecure) {
    error('S3 credentials contain a known insecure default value');
  } else {
    console.log('  OK: S3 credentials');
  }
}

// Check CORS
const corsOrigins = process.env.CORS_ORIGINS;
if (!corsOrigins || corsOrigins.trim() === '') {
  warn('CORS_ORIGINS is not configured.');
} else {
  console.log('  OK: CORS_ORIGINS');
}

// Summary
console.log('---');
if (hasErrors) {
  console.error('FAILED: Fix the errors above before deploying to production.');
  process.exit(1);
} else if (hasWarnings) {
  console.warn('PASSED with warnings. Review before production deployment.');
} else {
  console.log('All checks passed.');
}
