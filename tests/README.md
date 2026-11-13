# Tests

Tests mirror the application seams:

- `backend/` — database, read models, actions, routes, parsing, sync, provider adapters, diagnostics, and runtime layout.
- `desktop/` — Electron lifecycle, preload/native IPC, and desktop-facing storage behaviour.
- `frontend/` — renderer, workflows, API behaviour, selection, wallpaper, error recovery, and view contracts.

Prefer a test at the module's external seam. Run `npm test` for the full suite, or use the backend/frontend scripts in `package.json` for a narrower loop.
