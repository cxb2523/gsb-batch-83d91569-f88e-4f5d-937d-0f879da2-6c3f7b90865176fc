# Package-signing keys

This directory holds the **public** halves of the keys that sign UnTangled's
package feed. The release workflow publishes them to
<https://bidhata.github.io/untangled/keys/> so routers can verify the feed.

| File | Type | Verifies |
|---|---|---|
| `untangled.pub` | usign (ed25519) public key | the **opkg** feed index (`Packages.sig`) — stable 23.05 / 24.10 |
| `untangled.pem` | EC P-256 (prime256v1) public key, PEM | **apk** packages and `packages.adb` — snapshot |

The **private** halves must never be committed. They live only in the
repository's GitHub Actions Secrets, where the release workflow reads them:

| Secret | Contents | Used by |
|---|---|---|
| `USIGN_KEY` | the usign *secret* key file (`untangled.key`) | `KEY_BUILD` → signs `Packages` |
| `APK_KEY`   | the EC *private* key PEM (`untangled.key.pem`) | `PRIVATE_KEY` → signs `.apk` + `packages.adb` |

`.gitignore` excludes `keys/*.key` and `keys/*.key.pem` as a safety net.

## Generating the keys (one time, by the maintainer)

Run from the repository root. `usign` is not a common host tool, so the first
command borrows it from the OpenWRT SDK container; `openssl` is local.

```sh
# opkg / usign keypair
docker run --rm -v "$PWD/keys:/k" -w /builder ghcr.io/openwrt/sdk:x86_64-23.05.5 \
  bash -c 'staging_dir/host/bin/usign -G -s /k/untangled.key -p /k/untangled.pub -c "UnTangled packages"'

# apk keypair — MUST be EC prime256v1. The OpenWRT build derives the public key
# with `openssl ec`, which rejects ed25519/RSA and would fail the whole build.
openssl ecparam -name prime256v1 -genkey -noout -out keys/untangled.key.pem
openssl ec -in keys/untangled.key.pem -pubout -out keys/untangled.pem
```

Then:

1. Add the two **private** files as repository secrets
   (Settings → Secrets and variables → Actions → New repository secret):
   `USIGN_KEY` ← contents of `keys/untangled.key`,
   `APK_KEY` ← contents of `keys/untangled.key.pem`.
2. Commit **only** `keys/untangled.pub` and `keys/untangled.pem`.
3. Back the private keys up somewhere safe. If they are lost, a new key must be
   issued and every user has to re-trust it — treat them like a root of trust.

Signing is optional: with the secrets unset, the workflow still builds and
publishes unsigned packages (users would then need `--allow-untrusted` for apk).

## One-time repository setup: enable GitHub Pages

The feed is served from GitHub Pages. The workflow token can **deploy** to a
Pages site but is not allowed to **create** one, so enable it once by hand:

**Settings → Pages → Build and deployment → Source: "GitHub Actions"**

Until this is done the `Publish package feed` job fails with
`Create Pages site failed ... Resource not accessible by integration`.

**Then allow release tags to deploy.** Enabling Pages auto-creates a
`github-pages` environment whose default policy only lets the `main` branch
deploy, so the tag-triggered release job is rejected with
`Tag "vX.Y.Z" is not allowed to deploy to github-pages due to environment
protection rules`. Fix once:

**Settings → Environments → github-pages → Deployment branches and tags →
"Selected branches and tags" → Add deployment branch or tag rule → Ref type:
Tag → pattern `v*`**

After both settings, open the failed run in the Actions tab and choose
**Re-run failed jobs** (the build artifacts are still attached, so no new
release is needed), or simply push the next tag.
