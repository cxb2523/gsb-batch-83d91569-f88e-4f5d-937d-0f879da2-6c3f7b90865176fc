# Applications

The `apps/` directory contains the four runtime surfaces of the desktop application:

- [`backend/`](backend/README.md) — Fastify child process, domain workflows, providers, and SQLite access.
- [`desktop/`](desktop/README.md) — Electron main process, lifecycle, preload bridge, and native IPC.
- [`frontend/`](frontend/README.md) — React renderer, workflows, API client, and views.
- [`runtime/`](runtime/README.md) — app-data paths and filesystem storage shared by desktop/backend code.

See [`docs/CODEBASE_MAP.md`](../docs/CODEBASE_MAP.md) for dependency direction and feature ownership.
