/**
 * LocalDockerProvider tests
 *
 * The provider has three contractual invariants that the scaler depends on:
 *
 *   1. The `RUNNER_ID` env var on the spawned container MUST equal the
 *      `id`/`ip` returned in RunnerInfo. The scaler links runners to
 *      heartbeats via these fields (scaler/index.ts:169) — break this and
 *      every freshly created runner gets marked dead 3 minutes later.
 *
 *   2. Containers MUST be labelled `crawlee-cloud.scaler-runner=true`, since
 *      listRunners() uses that label to filter our containers from anything
 *      else on the host.
 *
 *   3. destroyRunner() MUST tolerate 304 (already stopped) and 404 (already
 *      gone) without throwing — these happen during normal scale-down race
 *      conditions and would otherwise turn a benign double-call into a noisy
 *      error in the scaler loop.
 *
 * These tests mock dockerode entirely so they're hermetic and run in <50ms.
 * They do NOT test the actual Docker integration (that's covered by the e2e
 * setup in the README).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import type Docker from 'dockerode';

const {
  createContainer,
  startContainer,
  stopContainer,
  removeContainer,
  listContainers,
  getContainer,
  listNetworks,
} = vi.hoisted(() => ({
  createContainer: vi.fn(),
  startContainer: vi.fn(),
  stopContainer: vi.fn(),
  removeContainer: vi.fn(),
  listContainers: vi.fn(),
  getContainer: vi.fn(),
  listNetworks: vi.fn(),
}));

vi.mock('dockerode', () => {
  return {
    default: class MockDocker {
      createContainer = createContainer;
      listContainers = listContainers;
      getContainer = getContainer;
      listNetworks = listNetworks;
    },
  };
});

// Import after mocking
const { LocalDockerProvider } = await import('../src/scaler/providers/local-docker.js');

function makeRunnerConfig() {
  return {
    region: 'unused',
    size: 'unused',
    sshKeyId: 'unused',
    userData: 'unused',
    tags: [],
  };
}

function envToMap(envArray: string[]): Record<string, string> {
  return Object.fromEntries(envArray.map((e) => e.split('=', 2) as [string, string]));
}

describe('LocalDockerProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Default: createContainer returns a fake container with .start()
    createContainer.mockImplementation((_opts: Docker.ContainerCreateOptions) => ({
      id: 'docker-container-id-abc123',
      start: startContainer,
    }));
    startContainer.mockResolvedValue(undefined);

    // Default: getContainer returns an object with stop/remove
    getContainer.mockImplementation((_id: string) => ({
      stop: stopContainer,
      remove: removeContainer,
    }));
    stopContainer.mockResolvedValue(undefined);
    removeContainer.mockResolvedValue(undefined);

    // Default: empty list
    listContainers.mockResolvedValue([]);

    // Reset env between tests
    delete process.env.LOCAL_RUNNER_IMAGE;
    delete process.env.LOCAL_RUNNER_API_BASE_URL;
    delete process.env.LOCAL_RUNNER_DATABASE_URL;
    delete process.env.LOCAL_RUNNER_REDIS_URL;
    // Default network so most tests skip network detection.
    process.env.DOCKER_NETWORK = 'test-network';
    listNetworks.mockResolvedValue([]);
  });

  describe('createRunner', () => {
    it('links RUNNER_ID env to RunnerInfo.id (heartbeat invariant)', async () => {
      const provider = new LocalDockerProvider();
      const info = await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      const env = envToMap(opts.Env ?? []);

      // The scaler's heartbeats.get(runner.id) lookup depends on this match.
      expect(env.RUNNER_ID).toBe(info.id);
      expect(info.ip).toBe(info.id);
    });

    it('names the container after the runner id (so destroyRunner can find it)', async () => {
      const provider = new LocalDockerProvider();
      const info = await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      expect(opts.name).toBe(info.id);
    });

    it('applies the scaler label and a runner-id label', async () => {
      const provider = new LocalDockerProvider();
      const info = await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      expect(opts.Labels?.['crawlee-cloud.scaler-runner']).toBe('true');
      expect(opts.Labels?.['crawlee-cloud.runner-id']).toBe(info.id);
    });

    it('mounts the docker socket so the runner can spawn nested containers', async () => {
      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      expect(opts.HostConfig?.Binds).toContain('/var/run/docker.sock:/var/run/docker.sock');
    });

    it('defaults DATABASE_URL to compose service names, NOT host process.env', async () => {
      // Simulate the API running on host with localhost URLs
      process.env.DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/crawlee_cloud';
      process.env.REDIS_URL = 'redis://localhost:6379';

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      const env = envToMap(opts.Env ?? []);

      // Critical: the runner container would crash if it inherited localhost URLs
      expect(env.DATABASE_URL).not.toContain('localhost');
      expect(env.REDIS_URL).not.toContain('localhost');
      expect(env.DATABASE_URL).toContain('@postgres:');
      expect(env.REDIS_URL).toContain('//redis:');
    });

    it('honors LOCAL_RUNNER_* env overrides', async () => {
      process.env.LOCAL_RUNNER_DATABASE_URL = 'postgresql://u:p@db.example.com/foo';
      process.env.LOCAL_RUNNER_REDIS_URL = 'redis://cache.example.com:6379';
      process.env.LOCAL_RUNNER_API_BASE_URL = 'http://192.168.1.50:3000';

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      const env = envToMap(opts.Env ?? []);

      expect(env.DATABASE_URL).toBe('postgresql://u:p@db.example.com/foo');
      expect(env.REDIS_URL).toBe('redis://cache.example.com:6379');
      expect(env.API_BASE_URL).toBe('http://192.168.1.50:3000');
    });

    it('places the container on DOCKER_NETWORK and propagates it to the runner env', async () => {
      process.env.DOCKER_NETWORK = 'my-custom-net';

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      const env = envToMap(opts.Env ?? []);

      expect(opts.HostConfig?.NetworkMode).toBe('my-custom-net');
      // Runner needs the same network so its nested actor containers attach correctly
      expect(env.DOCKER_NETWORK).toBe('my-custom-net');
    });

    it('starts the container after creating it', async () => {
      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      expect(createContainer).toHaveBeenCalledOnce();
      expect(startContainer).toHaveBeenCalledOnce();
    });

    it('returns status="creating" so the heartbeat can flip it later', async () => {
      const provider = new LocalDockerProvider();
      const info = await provider.createRunner(makeRunnerConfig());

      // 'creating' is the only correct initial status — heartbeats arrive ~30s after start
      expect(info.status).toBe('creating');
      expect(info.activeRuns).toBe(0);
    });
  });

  describe('destroyRunner', () => {
    it('stops and removes the container', async () => {
      const provider = new LocalDockerProvider();
      await provider.destroyRunner('local-abc');

      expect(getContainer).toHaveBeenCalledWith('local-abc');
      expect(stopContainer).toHaveBeenCalledOnce();
      expect(removeContainer).toHaveBeenCalledWith({ force: true });
    });

    it('tolerates 304 (container already stopped) without throwing', async () => {
      stopContainer.mockRejectedValueOnce(
        Object.assign(new Error('not modified'), { statusCode: 304 })
      );

      const provider = new LocalDockerProvider();
      await expect(provider.destroyRunner('local-abc')).resolves.toBeUndefined();
      expect(removeContainer).toHaveBeenCalled(); // still tries to remove
    });

    it('tolerates 404 (container already gone) on both stop and remove', async () => {
      stopContainer.mockRejectedValueOnce(
        Object.assign(new Error('not found'), { statusCode: 404 })
      );
      removeContainer.mockRejectedValueOnce(
        Object.assign(new Error('not found'), { statusCode: 404 })
      );

      const provider = new LocalDockerProvider();
      await expect(provider.destroyRunner('local-abc')).resolves.toBeUndefined();
    });

    it('rethrows unexpected errors from stop', async () => {
      stopContainer.mockRejectedValueOnce(Object.assign(new Error('boom'), { statusCode: 500 }));

      const provider = new LocalDockerProvider();
      await expect(provider.destroyRunner('local-abc')).rejects.toThrow('boom');
    });

    it('rethrows unexpected errors from remove', async () => {
      removeContainer.mockRejectedValueOnce(
        Object.assign(new Error('disk full'), { statusCode: 500 })
      );

      const provider = new LocalDockerProvider();
      await expect(provider.destroyRunner('local-abc')).rejects.toThrow('disk full');
    });
  });

  describe('listRunners', () => {
    it('filters containers by the scaler-runner label', async () => {
      const provider = new LocalDockerProvider();
      await provider.listRunners();

      expect(listContainers).toHaveBeenCalledWith(
        expect.objectContaining({
          all: true,
          filters: { label: ['crawlee-cloud.scaler-runner=true'] },
        })
      );
    });

    it('maps running containers to status="ready"', async () => {
      listContainers.mockResolvedValueOnce([
        {
          Id: 'docker-internal-id-1',
          Created: 1700000000,
          State: 'running',
          Labels: { 'crawlee-cloud.runner-id': 'local-xyz' },
        },
      ]);

      const provider = new LocalDockerProvider();
      const runners = await provider.listRunners();

      expect(runners).toHaveLength(1);
      expect(runners[0].id).toBe('local-xyz'); // runner-id label, NOT docker's internal id
      expect(runners[0].ip).toBe('local-xyz');
      expect(runners[0].status).toBe('ready');
    });

    it('maps non-running containers to status="draining" so the scaler reaps them', async () => {
      listContainers.mockResolvedValueOnce([
        {
          Id: 'docker-internal-id-2',
          Created: 1700000000,
          State: 'exited',
          Labels: { 'crawlee-cloud.runner-id': 'local-dead' },
        },
      ]);

      const provider = new LocalDockerProvider();
      const runners = await provider.listRunners();

      expect(runners[0].status).toBe('draining');
    });

    it('falls back to docker container Id when runner-id label is missing', async () => {
      listContainers.mockResolvedValueOnce([
        {
          Id: 'docker-internal-id-3',
          Created: 1700000000,
          State: 'running',
          Labels: {},
        },
      ]);

      const provider = new LocalDockerProvider();
      const runners = await provider.listRunners();

      expect(runners[0].id).toBe('docker-internal-id-3');
    });
  });

  describe('network resolution', () => {
    beforeEach(() => {
      // These tests drive the auto-detection path, so the env-var
      // override from the outer beforeEach must be cleared.
      delete process.env.DOCKER_NETWORK;
    });

    it('honors DOCKER_NETWORK when set, no detection needed', async () => {
      process.env.DOCKER_NETWORK = 'explicit-net';

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      expect(listNetworks).not.toHaveBeenCalled();
      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      expect(opts.HostConfig?.NetworkMode).toBe('explicit-net');
    });

    it('auto-detects when exactly one compose-managed network exists', async () => {
      listNetworks.mockResolvedValue([
        { Name: 'bridge', Labels: null },
        { Name: 'host', Labels: null },
        {
          Name: 'crawlee-platfrom_default',
          Labels: { 'com.docker.compose.project': 'crawlee-platfrom' },
        },
      ]);

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());

      const opts = createContainer.mock.calls[0][0] as Docker.ContainerCreateOptions;
      expect(opts.HostConfig?.NetworkMode).toBe('crawlee-platfrom_default');
    });

    it('throws a helpful error when no compose network is found', async () => {
      listNetworks.mockResolvedValue([
        { Name: 'bridge', Labels: null },
        { Name: 'host', Labels: null },
      ]);

      const provider = new LocalDockerProvider();
      await expect(provider.createRunner(makeRunnerConfig())).rejects.toThrow(
        /Cannot determine Docker network.*\(none found\)/s
      );
    });

    it('throws and lists candidates when multiple compose networks exist (ambiguous)', async () => {
      listNetworks.mockResolvedValue([
        { Name: 'projA_default', Labels: { 'com.docker.compose.project': 'projA' } },
        { Name: 'projB_default', Labels: { 'com.docker.compose.project': 'projB' } },
      ]);

      const provider = new LocalDockerProvider();
      await expect(provider.createRunner(makeRunnerConfig())).rejects.toThrow(
        /projA_default.*projB_default/s
      );
    });

    it('caches the resolved network across calls (does not re-list every createRunner)', async () => {
      listNetworks.mockResolvedValue([
        {
          Name: 'crawlee-platfrom_default',
          Labels: { 'com.docker.compose.project': 'crawlee-platfrom' },
        },
      ]);

      const provider = new LocalDockerProvider();
      await provider.createRunner(makeRunnerConfig());
      await provider.createRunner(makeRunnerConfig());
      await provider.createRunner(makeRunnerConfig());

      expect(listNetworks).toHaveBeenCalledTimes(1);
    });
  });
});
