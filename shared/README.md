# Shared contract

`shared/` is the narrow contract shared by the backend, desktop-adjacent code, and renderer. It contains TypeScript payload types, domain enums, limits, and constants.

Keep this directory dependency-light. It must not import Fastify, Electron, React, SQLite, filesystem adapters, or application-specific modules.
