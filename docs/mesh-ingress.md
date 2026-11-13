# Deploy the public Mesh ingress

The public Mesh ingress lets non-interactive reporting machines reach a private OpenAI Sites hub without receiving the Site's shared bypass credential. It is a stateless, allowlisted reverse proxy under `mesh-ingress/`.

## Security boundary

The ingress forwards only:

- `POST /api/mesh/enroll` for a ten-minute, one-use enrollment code;
- `POST /api/mesh/ingest` for signed snapshots;
- `POST /api/mesh/usage` for signed owner-scoped reads.

It does not expose `/admin`, the dashboard, Sites authentication, arbitrary paths, query strings, cookies, redirects, or client-supplied authorization headers. It enforces JSON-only requests, route-specific byte limits, enrollment and per-node rate limits, non-cacheable responses, and generic fail-closed upstream errors.

The private Sites hub remains authoritative. It validates the enrollment code, records the machine's public Ed25519 key, verifies signatures and timestamps, rejects replayed sequence numbers, scopes reads to the enrolled owner, and enforces revocation.

## Credentials

Only the ingress has `SITES_UPSTREAM_AUTH_TOKEN`. Store it as an encrypted Cloudflare Worker secret. Never put it in `wrangler.jsonc`, source control, documentation, a machine configuration, or an agent prompt.

Reporting machines receive only:

- the public ingress URL as `MESH_HUB_URL`;
- a fresh `MESH_ENROLLMENT_CODE`, removed after successful enrollment;
- their own locally generated private key inside `MESH_AGENT_STATE_PATH`.

## Validate locally

Requires Node.js 22.13 or newer:

```bash
cd mesh-ingress
npm ci
npm run check
```

For local Wrangler testing, copy `.dev.vars.example` to the ignored `.dev.vars` file and replace the placeholder. Never use a production secret in an untrusted development environment.

The committed `wrangler.example.jsonc` is intentionally generic. The real
`wrangler.jsonc` is ignored because its Worker name, private Site origin, and
rate-limit namespace IDs belong to one deployment.

## Deploy

Authenticate Wrangler to the intended Cloudflare account, then from
`mesh-ingress/` copy the template to the ignored deployment file:

```bash
cp wrangler.example.jsonc wrangler.jsonc
```

On PowerShell, use `Copy-Item wrangler.example.jsonc wrangler.jsonc`.

Before deploying, replace the Worker name and `MESH_UPSTREAM_ORIGIN` with this
user's own Worker name and exact private Site origin. Keep the two
`namespace_id` values distinct within that Cloudflare account. Then run:

```bash
npx wrangler secret put SITES_UPSTREAM_AUTH_TOKEN --config wrangler.jsonc
npm run deploy
```

Enter the private Site bypass value only at Wrangler's secret prompt. Never
commit the generated `wrangler.jsonc` or copy another user's origin, Worker
configuration, or bypass value.

Record the resulting HTTPS Worker URL and verify:

```bash
curl --fail --silent --show-error https://your-mesh-ingress.example/healthz
```

The health response must be HTTP 200. Requests to `/admin`, `/dashboard`, unknown paths, query-string variants, and non-POST Mesh methods must fail.

## Enroll a new machine

1. Sign in to the private Site and open `/admin`.
2. Select **Add a machine** immediately before installation.
3. Configure the machine with the ingress URL and generated one-time code.
4. Start the agent and verify enrollment plus first synchronization.
5. Remove `MESH_ENROLLMENT_CODE` from persistent configuration.
6. Confirm that `/admin` shows the new machine and its recent synchronization time.

No private Site token is ever copied to the machine.

## Migrate existing machines

1. Deploy and validate the ingress using the currently valid upstream credential.
2. On each enrolled machine, preserve `MESH_AGENT_STATE_PATH`, replace `MESH_HUB_URL` with the ingress URL, remove `MESH_SITES_BYPASS_TOKEN`, and restart.
3. Verify that each existing identity synchronizes through the ingress without re-enrollment.
4. When every machine has migrated, rotate the Site bypass token during a short maintenance window and immediately update `SITES_UPSTREAM_AUTH_TOKEN` on the ingress.
5. Verify ingress health, a signed synchronization, a signed centralized read, and rejection of the old Site token.

Do not rotate the old token before the ingress is deployed and the update procedure is ready, because that would interrupt current agents.

## Revocation and recovery

Revoking a machine under `/admin` immediately blocks its signed uploads and reads at the private hub. The ingress cannot override that decision. If a machine loses its state file, revoke the old identity, generate a new one-time code, and enroll the replacement identity.

If the ingress is unavailable, restore it or roll back its deployment. Never distribute its upstream credential to reporting machines as a workaround.
