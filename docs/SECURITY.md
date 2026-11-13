# Security model

UnTangled is a browser app that talks to the router's own `rpcd` over
`/ubus` (the same mechanism LuCI uses). What a logged-in session may do is
decided entirely by the rpcd ACL the package installs:
`openwrt/files/usr/share/rpcd/acl.d/untangled.json`.

## What the admin role can do

- **UCI**: read and write any config. This is a router admin UI, so this is
  the same breadth as a full LuCI install.
- **Files and commands**: only an explicit allow-list. Every `file.read`,
  `file.write` and `file.exec` grant names an exact path or command line,
  e.g. `/etc/init.d/sqm restart`,
  `/sbin/sysupgrade -b /tmp/untangled-backup.tar.gz`, `/etc/crontabs/root`,
  or a narrow glob where the argument is user data: `/etc/openvpn/*.ovpn`,
  `/proc/*/mounts`, `/usr/bin/etherwake -i *`, `/bin/ping -c 3 -w 5 [!-]*`.
  There is no `/bin/sh`, no `file.list`, no `file.remove`, no generic exec.
  rpcd matches the resolved executable and then the full command line, so
  `sh -c`, `../` traversal and flag injection into the ping plugin are all
  rejected with "Access denied".
- **rpc-sys**: only `upgrade_test`, `upgrade_start`, `upgrade_clean`
  (firmware flashing). `factory` reset is not granted.
- **cgi-io**: `upload` (firmware image / backup restore to fixed `/tmp`
  paths) and `download` (the backup archive) only.
- **Other ubus writes**: `luci setPassword` (router password), `network
  reload/restart`, `network.interface.* up/down`, `network.wireless up/down`,
  `session destroy`, and the `untangled.mesh` helper's methods (which rewrite
  SSID, key and 802.11r on the AP interfaces when you join or lead a mesh;
  the helper ships only with the `untangled-mesh` package).

## What the read-only role can do

Dashboards, status, logs and `uci get system`. No file access, no exec, and
no `uci get` of `wireless`, `network` or any other config that holds
credentials (Wi-Fi keys, PPPoE passwords, WireGuard private keys).

## Transport

`untangled-full` turns on `uhttpd`'s HTTP-to-HTTPS redirect (307) with the
self-signed certificate `px5g` generates on first boot, the same way
`luci-ssl` works. The core package is HTTP-only on purpose (it pulls no TLS
library) and is meant for installs behind an existing HTTPS front-end or on a
trusted LAN. The redirect is only enabled when `uhttpd` already has an HTTPS
listener configured, so it can never lock you out of the HTTP UI.

## Package signing

The feed and release packages are signed with the project's usign / apk key
(usign fingerprint `ebd6eddd72aa9d25`). Trusting the key is what lets `opkg`
and `apk` verify the packages came from this project and were not altered in
transit; it grants nothing else. The public key is in `keys/` and on the
feed site under `/keys/`. If you would rather not trust it, download the
`.ipk`/`.apk` from a release and install it by file.

## Verifying this yourself

The ACL is exercised against real OpenWRT rootfs containers (23.05 and
snapshot) with `scripts/acl-probe.sh`, run by the maintainer before a release
(it is not yet part of the CI workflow): an allow-list probe (every command the UI runs)
and a deny probe (`/bin/sh -c`, `/etc/shadow`, path traversal, non-granted
init scripts, `sysupgrade` with other arguments, `apk add`, `file.list`,
`file.remove`). Issues: https://github.com/bidhata/untangled/issues
