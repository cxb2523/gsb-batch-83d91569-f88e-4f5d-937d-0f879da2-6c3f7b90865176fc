# Submitting UnTangled to `openwrt/packages` (draft)

This directory holds a **draft** Makefile for a future pull request to the
official community feed <https://github.com/openwrt/packages>. It is NOT used by
this project's release CI (that uses `../Makefile`). Nothing here ships today.

## Why it's separate from `../Makefile`

| | `../Makefile` (our CI) | `upstream/Makefile` (this draft) |
|---|---|---|
| Source | local feed dir with `files/` + a freshly built `dist/` copied in | pinned release **tarball** fetched via `PKG_SOURCE` + `PKG_HASH` |
| Build | our CI runs `npm run build` before packaging | **no network at build** — tarball must already contain `dist/` |
| Install from | `./files/...` | `$(PKG_BUILD_DIR)/...` |

The OpenWRT buildbots are hermetic (no internet during compile), so a JS UI must
ship **prebuilt**. We fetch a "product" tarball, not GitHub's source archive.

## Per-release steps

1. Build the product tarball in CI and attach it to the GitHub release
   (`untangled-<ver>.tar.gz`, top-level `dist/ files/ files-mesh/ LICENSE`):

   ```sh
   VER=0.1.9
   npm ci && npm run build
   mkdir -p pkg/untangled-$VER
   cp -r dist LICENSE pkg/untangled-$VER/
   cp -r openwrt/files openwrt/files-mesh pkg/untangled-$VER/
   tar -C pkg -czf untangled-$VER.tar.gz untangled-$VER
   sha256sum untangled-$VER.tar.gz        # -> PKG_HASH
   ```

2. Update `PKG_VERSION` and `PKG_HASH` in `upstream/Makefile`.

## Opening the PR (when the package is ready — not during beta)

1. Fork `openwrt/packages`, create `net/untangled/Makefile` from this draft.
2. `make package/untangled/check` and a test build (`PKGARCH:=all` helps — one
   build covers all arches).
3. Open the PR; respond to maintainer review.

## Readiness gate

Do **not** submit while the project is a hardware-unvalidated beta. Upstream
expects a stable, tested package. Validate the flagship screens on real routers
and finish/gate the half-done paths (Guest provisioning, VPN create, mesh
multi-node, Extend-Wi-Fi LAN sharing) first. Our own signed feed
(<https://bidhata.github.io/untangled/>) is the right channel until then.
