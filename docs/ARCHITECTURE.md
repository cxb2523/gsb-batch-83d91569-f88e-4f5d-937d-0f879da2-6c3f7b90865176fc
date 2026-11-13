# UnTangled — Architecture

*A web interface for OpenWRT, offered as an easier alternative to LuCI, for non-technical and technical users alike.*

Status: describes the **shipped** architecture as of v0.1.13 (2026-11-10). Facts that another file owns are linked, not repeated: install, sizes and supported versions in [README.md](../README.md); packages and dependencies in [openwrt/Makefile](../openwrt/Makefile); what a session may do in [SECURITY.md](SECURITY.md) and the [rpcd ACL](../openwrt/files/usr/share/rpcd/acl.d/untangled.json); the plugin contract in [PLUGINS.md](PLUGINS.md).

Target platform: OpenWRT 23.05 or newer (opkg on stable releases, apk on snapshot).

---

## 1. Problem, goals and non-goals

**Problem.** OpenWRT's stock interface was built for engineers. A household that bought a router to get Wi-Fi should be able to rename the network, set up a guest network, pause a child's device or extend coverage without learning what a wifi-iface or a firewall zone is.

### Goals
- One interface a non-technical user can operate by task ("Extend Wi-Fi", "Open access to a device") and a technical user can drive fully (the settings the UI exposes, Advanced-details disclosures, command palette).
- Runs on-device and offline: no cloud account, no font, asset or script fetched at runtime. One recorded exception, see §3.
- Small enough to coexist with LuCI on common router flash (free-flash floor in README).
- Extensible at runtime by plugins ([PLUGINS.md](PLUGINS.md)).

### Non-goals
- Replacing the OpenWRT backend. UCI, ubus, rpcd and uhttpd are reused unchanged.
- Replacing LuCI. UnTangled installs beside it and touches no LuCI files.
- Proprietary vendor features (AiProtection, AiMesh). OpenWRT equivalents are mapped where they exist (adblock, banIP, SQM, dawn).
- Fleet or multi-router management.

---

## 2. Design principles

1. **Task-based default path.** Jargon stays out of the main flow; flows pick defaults and expose them under Advanced details.
2. **Depth on demand.** Every screen has an Advanced details disclosure; every field has a `?` help tooltip.
3. **Live, not hardcoded.** Devices, radios, clients and installed features are read from the router at render time. A feature whose backing package is absent degrades to an "install X" card instead of a broken screen.
4. **Offline-first.** System font stack; all CSS, JS and icons in the bundle.
5. **Dual theme.** Light (default) and dark, via CSS custom-property tokens.

---

## 3. System architecture

```text
Browser (SPA)  ──HTTP(S)──▶  uhttpd  ──▶  /ubus  (JSON-RPC, uhttpd-mod-ubus)
                               │               │
                        static /www/untangled  ▼
                                             ubusd ◀── rpcd (session login + ACL,
                                               │         plugins: file, iwinfo, luci, rpcsys)
                             ┌─────────────────┼──────────────────┐
                          netifd           UCI (/etc/config)   system / hostapd / log
```

**Kept as-is:** ubusd, netifd, UCI, rpcd, uhttpd. **Replaced:** the UI, a static single-page app under `/www/untangled/` that talks to `POST /ubus` only. The one non-/ubus endpoint is `cgi-io` (`/cgi-bin/cgi-upload`, `/cgi-bin/cgi-download`) for firmware upload and backup download, shipped with the full package.

**Why this shape, and what was rejected**
- *Fork or re-theme LuCI* — rejected: the task-based flows need different screens, not different CSS, and LuCI's Lua/ucode page model would carry its complexity into every screen.
- *A daemon or server-rendered pages* — rejected: a daemon is a new privileged process to audit and keep resident on a router with 64-128 MB of RAM; static files cost nothing at rest and the `/ubus` contract already exists for LuCI's JS client.
- *Event push (WebSocket or an rpcd event bridge)* — rejected for now: uhttpd-mod-ubus is request/response and polling at 1-5 s has not shown a load problem; revisit only with a measurement.

**Write path.** Reads are `uci get`, `network.*`, `system`, `hostapd.*`, `iwinfo`, `luci-rpc`, `log`. Writes stage with `uci set/add/delete`, then:
- connectivity-risky configs (`wireless`, `network` for WAN/LAN, `firewall` zones and DMZ) go through `uci apply { rollback: true, timeout }`; the UI shows a countdown shorter than the router's timeout and calls `uci confirm` (keep) or `uci rollback` (revert). If the browser never confirms, the router reverts on its own, so a bad Wi-Fi or WAN change cannot lock the user out;
- everything else uses plain `uci apply`;
- some features then kick their service (`/etc/init.d/<svc> reload|restart`) through a path-scoped `file.exec`. Those reloads sit outside the rollback contract: a rollback restores UCI but not necessarily the running service.

Two liabilities of the rollback flow: closing the tab during the countdown reverts a good change; and UCI staging is shared with LuCI, so an apply from one UI commits what the other staged. Both are accepted.

**Offline exception.** When the WAN address is private or carrier-NAT, the browser (never the router) asks a public echo service for the internet-visible address so the Network Map can explain why port forwarding will not work. Best-effort, 5 s timeout, null when offline.

---

## 4. Frontend

Svelte 5 + Vite + TypeScript, no component library, no CDN, no web fonts; one hashed JS chunk and one CSS file under a 300 KB gzipped ceiling (measured size in README). Served at `/untangled/`; an optional Administration toggle makes it uhttpd's index page. Dev: `ROUTER=<ip> npm run dev` proxies `/ubus` to a real router; without `ROUTER` a mock backend serves fixtures.

---

## 5. Backend integration

### 5.1 Transport and session
All calls go to `POST /ubus` as JSON-RPC 2.0 `call` with the session id as the first param. Login is `session login`; the token lives in module memory and is discarded on reload. rpcd's idle timeout is the session control; after it, calls fail with permission denied and the user signs in again. The token travels in the JSON body, not a cookie, so a cross-site form post cannot carry it.

### 5.2 Access control
One ACL file, two groups: `untangled` (admin) and `untangled-readonly`. Admin has unrestricted UCI and a path-scoped allow-list of files and commands; read-only has dashboards and logs only. Full description in [SECURITY.md](SECURITY.md). The read-only group is backend-only today: the UI is not role-aware, and a login is assigned to a group by editing `/etc/config/rpcd` ([openwrt/README.md](../openwrt/README.md)). Anything the UI runs on the router must be named in the ACL; a new feature that execs a command adds its exact command line there.

### 5.3 Data sources per screen

| Screen | ubus / source |
|---|---|
| Network Map, Devices | `system board/info`, `network.interface dump`, `network.device status`, `luci-rpc getHostHints` + `getDHCPLeases`; Wi-Fi band and signal from `hostapd.<ifname> get_clients`, falling back to `iwinfo assoclist`; reservations and blocks in `uci dhcp`/`firewall`; Wake-on-LAN via `etherwake` |
| Traffic Monitor | `network.device status` counters polled at 1 s |
| Usage History | `vnstat --json`, `nlbw` (each degrades independently) |
| Wireless, Guest | `uci wireless` (+ `network`, `dhcp`, `firewall` for guest provisioning), `network.wireless status` |
| Extend Wi-Fi | `iwinfo scan`; joins as a client (`sta`) on `wwan`; no relayd bridge |
| Parental Controls | fw4 time rules by MAC in `uci firewall` |
| Network Protection | `uci adblock`, `uci banip` enable flags; link to AdGuard Home when present |
| Internet (WAN), LAN, IPv6 | `uci network`, `uci dhcp`; WAN protocols dhcp / pppoe / static |
| Dynamic DNS, QoS, UPnP, Dual WAN | `uci ddns`, `sqm`, `upnpd`, `mwan3` + their init scripts |
| Port Forwarding, Firewall, DMZ | `uci firewall` redirects and zones |
| VPN | `uci network` WireGuard interfaces and peers (paste keys; no key generation), `uci openvpn` + profile written with `file write` |
| Tailscale | `tailscale status/up/down` via `file.exec` |
| Administration | `uci system`, `luci setPassword`, scheduled reboot in `/etc/crontabs/root`, default-page toggle in `uci uhttpd` |
| Firmware | upload via `cgi-io`; `rpc-sys upgrade_test` then `upgrade_start`; backup `sysupgrade -b` + `cgi-io` download; restore `sysupgrade -r` |
| USB Storage | `/proc/mounts`, `uci ksmbd`, `uci minidlna` |
| Software | `apk list --installed` or `opkg list-installed`, read-only |
| System Log | `log read` |
| Mesh Wi-Fi (plugin) | `untangled.mesh` rpcd helper from the `untangled-mesh` package |

Polling: Network Map 5 s, Traffic Monitor 1 s, stopped when the screen unmounts.

---

## 6. Plugins

A plugin is an ES module exporting `{ id, title, group, icon, mount(container, api) }`, listed in `plugins/index.json` and loaded after login. It receives the host API (ubus/uci calls, toast, navigate, theme). A plugin runs with the full session of the logged-in user, so it is as trusted as the admin: install plugins only from signed feeds. Full contract and the two shipped plugins (Ping, Mesh Wi-Fi) in [PLUGINS.md](PLUGINS.md).

---

## 7. Packaging

Three packages from one source ([openwrt/Makefile](../openwrt/Makefile)): `untangled` (core: UI + ACL + uci-defaults; HTTP only), `untangled-full` (meta: Wi-Fi scan, firmware/backup, Wake-on-LAN, HTTPS redirect) and `untangled-mesh` (rpcd helper + dawn/umdns). Rule: core may assume `uhttpd-mod-ubus`, `rpcd-mod-file` and `rpcd-mod-luci`; every other backend is optional and detected per screen. Releases are built by the GitHub workflow into a signed opkg/apk feed (install steps and key in README).

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Lock-out after a bad Wi-Fi, WAN, LAN or firewall change | apply-with-rollback plus UI confirm (§3); router reverts on its own if unconfirmed |
| Bad firmware image | `rpc-sys upgrade_test` must pass before `upgrade_start`; keep-settings toggle; explicit caution |
| Service reload fails after a successful UCI apply | the reload error is surfaced to the user instead of swallowed |
| A session can run arbitrary commands as root | no generic exec; every file path and command line is allow-listed and probed in containers before release (SECURITY.md) |
| Core package sends credentials in clear text | core is for trusted LANs or behind an HTTPS front-end; the full package redirects to HTTPS |
| Not enough flash | free-flash floor stated in README; core has four small dependencies |

---

## 9. Decisions taken

| Decision | Choice |
|---|---|
| Framework | Svelte 5 + Vite + TypeScript (bundle size) |
| Serve path | `/untangled/` beside LuCI; optional default-page toggle |
| Traffic history | poll-only live counters; history via optional vnstat + nlbwmon |
| Privileged operations | path-scoped `file.exec` grants in the ACL; no custom rpcd helper except `untangled.mesh` |
| Package manager UI | read-only list; install and remove left to opkg/apk |
| Plugin discovery | static `plugins/index.json` shipped with core |
| Minimum target | see README requirements |

Roadmap and next items: [README.md](../README.md#status--roadmap).
