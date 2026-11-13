# Security

## Model

MeshAtlas is a **read-only** observer.

- **Network exposure.** By default it binds to the machine's Tailscale IPv4 address, so only devices your tailnet ACLs
  allow can reach it. `host = "0.0.0.0"` exposes it on every interface; do that only behind a firewall and with a
  token. For HTTPS and identity, put it behind `tailscale serve`.
- **Optional token.** `token` / `MESHATLAS_TOKEN` requires the token once per browser (`?token=…`), then a
  `HttpOnly; SameSite=Strict` cookie. API clients can send `Authorization: Bearer <token>`.
- **Commands on the hub.** `tailscale status --json`, `tailscale ping`, `tailscale debug derp-map`,
  `tailscale netcheck`, `ping`, and `ssh` with `BatchMode=yes`.
- **Commands on SSH targets.** A Python script fed to `python3 -` on stdin; nothing is written to the remote disk.
  It runs `docker ps`, `docker stats`, `systemctl list-units`, reads `/proc`, `/etc/os-release` and filesystem usage,
  and (with mesh enabled) `tailscale ping`. It tries `sudo -n docker` only if plain `docker` is denied, and never
  prompts for a password. It never runs `docker inspect` and never reads environment variables.
- **What reaches the browser.** Node names, Tailscale IPs, OS, container names/images/ports, unit names and
  descriptions, metrics and events. SSH targets and external IP addresses of tailnet peers are not sent.
- **Headers.** A strict Content-Security-Policy (`script-src 'self'`), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `frame-ancestors 'none'`.
- **No telemetry.** MeshAtlas makes no outbound requests except the optional Uptime Kuma status page you configure.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Security" → "Report a vulnerability") rather than a public
issue. You will get a reply within a week.
