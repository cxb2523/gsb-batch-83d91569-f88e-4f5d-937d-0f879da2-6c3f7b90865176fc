# Frontend

This directory contains the React renderer loaded by Vite.

- `src/App.tsx` — shell and view selection.
- `src/views/` — screen and presentation modules.
- `src/api/` — backend HTTP client and request helpers.
- `src/use*Workflow.ts` and workflow modules — state transitions and side effects.
- `src/release*`, `src/completed*`, `src/wallpaper*`, and related helpers — feature-specific renderer seams.
- `index.html`, `src/main.tsx`, and `src/styles.css` — renderer bootstrap and presentation foundation.

Views should render state and emit user intent. Put orchestration in workflows and transport details in `api/`.
