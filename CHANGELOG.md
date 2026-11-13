# Changelog

## 0.1.0 — unreleased

First public release.

- Zero-config discovery from `tailscale status`; locations from the DERP map, with a `netcheck` fallback for hubs
  on custom DERP regions.
- Built-in latency: `tailscale ping` from the hub, full mesh from SSH nodes, ICMP for external servers.
- Read-only SSH collection: containers, systemd units, CPU, memory, disks.
- The remote collector JSON now carries an additive `collection` field reporting a verifiable outcome
  (`ok` / `missing` / `error` / `parse_error`, plus `skipped`) for docker `ps`, docker `stats`, the
  systemd system and user scopes, and system information. Legacy fields (`ok`, `sys`, `docker`,
  `services`, `hostname`, `elapsed`) keep their exact meaning and structure, so existing callers are
  unaffected; a `docker stats` failure no longer looks like a `docker ps` failure.
- Map with direct / relayed / ICMP links, mesh view and latency matrix; node detail pages; ⌘K search; issues list;
  per-browser settings; browser notifications; English and Chinese.
- SQLite history (7 days): latency, CPU / memory, availability, events.
- `meshatlas run | init | demo | check`, Docker image, systemd unit, static demo site.
