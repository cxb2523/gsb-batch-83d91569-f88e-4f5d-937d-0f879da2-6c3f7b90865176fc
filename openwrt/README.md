# Packaging UnTangled for OpenWRT

UnTangled ships as a prebuilt static SPA served by `uhttpd`, talking to `ubus`/`rpcd`.
Three packages are built from one source:

| Package | What it adds | Typical new bytes on disk* |
|---|---|---|
| **`untangled`** | Core: serve the UI + `/ubus`, session auth, file ops. **HTTP only.** | ~100 KB app (compressed on flash) + ~95 KB deps (if not already present) |
| **`untangled-full`** | Core **+** Wi-Fi scan, firmware/backup, **HTTPS by default** | + up to ~300 KB (often ~0 — a TLS stack is usually already on Wi-Fi images) |

\* Installed (uncompressed) sizes. Real flash use is lower: the overlay
(JFFS2/UBIFS) and SquashFS compress files, so the plain ~330 KB of app assets
occupy ~65 KB on flash. Don't pre-gzip into the package — stock uhttpd won't
serve precompressed files and the filesystem already compresses them.

## 1. Build the SPA

```sh
npm install
npm run build                 # -> dist/   (ship these plain files)
# optional, only for an nginx front-end with gzip_static:
npm run build:gz              # also writes dist/**/*.gz
```

## 2. Stage files for the package

```sh
mkdir -p openwrt/files/www/untangled
cp -r dist/* openwrt/files/www/untangled/     # plain assets; skip *.gz for apk/ipk
```

`openwrt/files/` also contains:
- `usr/share/rpcd/acl.d/untangled.json` — ACL groups `untangled` (full) and `untangled-readonly`.
- `etc/uci-defaults/90-untangled` — sets uhttpd's `/ubus` prefix on first boot.
- `www/untangled-home.html` — the optional landing page used by the "default page" toggle.

Sibling payload directories: `openwrt/files-full/` (`91-untangled-https`, the HTTPS redirect for `untangled-full`) and `openwrt/files-mesh/` (the `untangled.mesh` rpcd helper + `92-untangled-mesh`).

## 3. Build the packages (OpenWRT SDK or buildroot)

Copy the `openwrt/` folder as `package/untangled` in an OpenWRT tree (or SDK), then:

```sh
make package/untangled/compile V=s      # builds untangled, untangled-full and untangled-mesh
```

Produces `untangled_<ver>_all.ipk` / `untangled-<ver>.apk` (core), the same for `untangled-full` (meta) and `untangled-mesh` (mesh backend).
- **23.05 and 24.10 (stable)** use `.ipk` (opkg).
- **Snapshot (main)** uses `.apk` (apk) — the only line that does.
Same payload, different archive format — installed size is identical.

## 4. Install

```sh
# minimal, HTTP-only:
opkg install untangled           # or: apk add untangled
# full feature set (HTTPS by default, Wi-Fi scan, firmware/backup, Wake-on-LAN):
opkg install untangled-full      # or: apk add untangled-full
```

The core package is HTTP-only. `untangled-full` pulls in TLS + `px5g` and its
`uci-defaults` turns on uhttpd's HTTP→HTTPS redirect (307), using the self-signed
certificate uhttpd generates on first boot — same as `luci-ssl`. The redirect is
only enabled if uhttpd already has a `listen_https` entry, so it cannot lock you
out. To go back to plain HTTP: `uci set uhttpd.main.redirect_https=0; uci commit
uhttpd; /etc/init.d/uhttpd restart`.

## 5. Grant a login the ACL group

In `/etc/config/rpcd`, give the admin login the `untangled` groups:

```
config login
    option username 'root'
    option password '$p$root'    # reads the hash from /etc/shadow
    list read  'untangled'
    list write 'untangled'
```

Then `/etc/init.d/rpcd restart`.

The `untangled` group grants unrestricted UCI (it is an admin UI) but only an
allow-list of exact files and command lines (a few narrow globs) — no shell, no `file.list`/`remove`, no
`rpc-sys factory`. `untangled-readonly` gets dashboards/logs only and cannot read
configs that hold credentials. Details: [`docs/SECURITY.md`](../docs/SECURITY.md).

## Coexisting with LuCI

Both read the same UCI config, so UnTangled installs safely alongside LuCI. Serve
UnTangled at `/untangled/` (or make it the default document root) and keep LuCI at
`/cgi-bin/luci` as a fallback while UnTangled matures.

## Dev against a real router

```sh
ROUTER=192.168.1.1 npm run dev
```

Vite proxies `/ubus` to `https://$ROUTER` (self-signed cert accepted), so the dev
server drives the live router.
