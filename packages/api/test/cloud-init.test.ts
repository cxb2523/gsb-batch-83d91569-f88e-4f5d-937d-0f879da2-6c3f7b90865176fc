/**
 * Tests for getCloudInitScript() — the bash script that bootstraps a
 * freshly-created cloud VM into a runner.
 *
 * This is the highest-leverage thing to test in the scaler: a bug here
 * means a Droplet boots, fails to start the runner, and silently never
 * heartbeats. The scaler then sees a "dead" runner, reaps it, creates a
 * replacement, and the cycle repeats — burning money while the queue
 * never drains.
 *
 * The script is bash, so we test what we can verify at the string level:
 *   - Required env vars are present in the rendered output
 *   - User-controlled values land in the right slots
 *   - The systemd unit references the right paths
 *   - Branching (the GHCR_TOKEN-conditional docker login) renders correctly
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { getCloudInitScript } from '../src/scaler/index.js';

const ENV_VARS = [
  'DATABASE_URL',
  'REDIS_URL',
  'SCALER_API_BASE_URL',
  'GHCR_TOKEN',
  'IMAGE_REGISTRY',
  'IMAGE_REGISTRY_USER',
  'IMAGE_REGISTRY_TOKEN',
];

const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const v of ENV_VARS) {
    savedEnv[v] = process.env[v];
    delete process.env[v];
  }
});

afterEach(() => {
  for (const v of ENV_VARS) {
    if (savedEnv[v] === undefined) delete process.env[v];
    else process.env[v] = savedEnv[v];
  }
});

describe('getCloudInitScript', () => {
  it('starts with a bash shebang and `set -e` for fail-fast bootstrapping', () => {
    const script = getCloudInitScript(2);
    expect(script.startsWith('#!/bin/bash')).toBe(true);
    expect(script).toContain('set -e');
  });

  it('embeds DATABASE_URL, REDIS_URL, and API_BASE_URL from process.env', () => {
    process.env.DATABASE_URL = 'postgresql://prod:secret@db.example.com/crawlee';
    process.env.REDIS_URL = 'redis://cache.example.com:6379';
    process.env.SCALER_API_BASE_URL = 'https://api.crawlee.cloud';

    const script = getCloudInitScript(5);

    expect(script).toContain('DATABASE_URL=postgresql://prod:secret@db.example.com/crawlee');
    expect(script).toContain('REDIS_URL=redis://cache.example.com:6379');
    expect(script).toContain('API_BASE_URL=https://api.crawlee.cloud');
  });

  it('embeds runsPerRunner as MAX_CONCURRENT_RUNS', () => {
    const script = getCloudInitScript(7);
    expect(script).toContain('MAX_CONCURRENT_RUNS=7');
  });

  it('locks down the env file with chmod 600', () => {
    // The env file contains DATABASE_URL with creds; world-readable is a
    // privilege-escalation vector if any local user lands on the box.
    const script = getCloudInitScript(2);
    expect(script).toContain('chmod 600 /etc/crawlee-runner.env');
  });

  it('creates a systemd unit that runs the runner with restart-on-failure', () => {
    const script = getCloudInitScript(2);
    expect(script).toContain('/etc/systemd/system/crawlee-runner.service');
    expect(script).toContain('ExecStart=/usr/bin/node packages/runner/dist/index.js');
    expect(script).toContain('Restart=always');
    expect(script).toContain('After=docker.service');
    expect(script).toContain('Requires=docker.service');
  });

  it('enables and starts the systemd unit', () => {
    const script = getCloudInitScript(2);
    expect(script).toContain('systemctl daemon-reload');
    expect(script).toContain('systemctl enable crawlee-runner');
    expect(script).toContain('systemctl start crawlee-runner');
  });

  describe('GHCR conditional', () => {
    it('renders a docker-login command when GHCR_TOKEN is set', () => {
      process.env.GHCR_TOKEN = 'ghp_secret123';
      const script = getCloudInitScript(2);
      expect(script).toContain('docker login ghcr.io -u github --password-stdin');
      expect(script).toContain('echo "ghp_secret123"');
    });

    it('renders a comment placeholder when GHCR_TOKEN is unset', () => {
      const script = getCloudInitScript(2);
      expect(script).toContain('# No GHCR token');
      expect(script).not.toContain('docker login ghcr.io');
    });
  });

  describe('image registry passthrough', () => {
    it('embeds IMAGE_REGISTRY/USER/TOKEN env vars when set', () => {
      process.env.IMAGE_REGISTRY = 'ghcr.io/crawlee-cloud';
      process.env.IMAGE_REGISTRY_USER = 'github';
      process.env.IMAGE_REGISTRY_TOKEN = 'ghp_secret';

      const script = getCloudInitScript(2);

      expect(script).toContain('IMAGE_REGISTRY=ghcr.io/crawlee-cloud');
      expect(script).toContain('IMAGE_REGISTRY_USER=github');
      expect(script).toContain('IMAGE_REGISTRY_TOKEN=ghp_secret');
    });

    it('renders empty values rather than the literal "undefined" when env is unset', () => {
      // A literal "undefined" in a bash assignment would be silently treated
      // as a string, which the runner would then try to use as a real
      // registry URL. Must default to empty.
      const script = getCloudInitScript(2);
      expect(script).not.toContain('=undefined');
      expect(script).toContain('IMAGE_REGISTRY=\n');
    });
  });

  it('curls the runner-ready endpoint at the end of the bootstrap', () => {
    process.env.SCALER_API_BASE_URL = 'https://api.example.com';
    const script = getCloudInitScript(2);
    // The trailing `|| true` ensures cloud-init doesn't fail if the API
    // is briefly unreachable — boot should still succeed.
    expect(script).toContain('curl -s -X POST "https://api.example.com/v2/internal/runner-ready"');
    expect(script).toContain('|| true');
  });

  describe('SCALER_INSECURE_TLS gate', () => {
    // The previous behavior — unconditionally setting NODE_TLS_REJECT_UNAUTHORIZED=0
    // on every runner — disabled cert verification on every outbound HTTPS call
    // (API, S3, registries, actor scraping). v0.8.1 made it opt-in. These tests
    // lock the new contract so the bypass cannot accidentally come back.
    it('does NOT set NODE_TLS_REJECT_UNAUTHORIZED when SCALER_INSECURE_TLS is unset', () => {
      const script = getCloudInitScript(2);
      expect(script).not.toContain('NODE_TLS_REJECT_UNAUTHORIZED');
    });

    it('does NOT set NODE_TLS_REJECT_UNAUTHORIZED when SCALER_INSECURE_TLS is "false"', () => {
      process.env.SCALER_INSECURE_TLS = 'false';
      const script = getCloudInitScript(2);
      expect(script).not.toContain('NODE_TLS_REJECT_UNAUTHORIZED');
    });

    it('emits NODE_TLS_REJECT_UNAUTHORIZED=0 in env file and systemd unit when SCALER_INSECURE_TLS=true', () => {
      process.env.SCALER_INSECURE_TLS = 'true';
      const script = getCloudInitScript(2);
      expect(script).toContain('NODE_TLS_REJECT_UNAUTHORIZED=0');
      expect(script).toContain('Environment=NODE_TLS_REJECT_UNAUTHORIZED=0');
    });
  });
});
