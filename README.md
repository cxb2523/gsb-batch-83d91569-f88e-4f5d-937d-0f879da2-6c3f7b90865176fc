# OpenUI x F1

A Formula 1 demo built on OpenUI: a "team radio" chat that answers with live charts, tables and F1 visuals, alongside Home, Standings, Drivers and Teams dashboards. All data comes from [OpenF1](https://openf1.org).

It grew out of the [conversational analytics cookbook](https://github.com/thesysdev/openui/tree/main/examples/cookbooks/conversational-analytics) in the OpenUI repo. The cookbook stays small and matches its [walkthrough](https://www.openui.com/cookbooks/conversational-analytics); this repo is the full demo that gets deployed.

## Run it

Needs Node 22.13 or later.

```bash
npm install
npm run generate:apiKey   # writes THESYS_API_KEY to .env.local
npm run snapshot:f1   # optional: cache finished 2026 sessions so the tools work offline
npm run dev
```

Open http://127.0.0.1:3000.

| Variable            | Default            | Purpose                                                    |
| ------------------- | ------------------ | ---------------------------------------------------------- |
| `THESYS_API_KEY`    | (required)         | OpenUI Gateway key, used only on the server                |
| `OPENUI_MODEL`      | `openai/gpt-5.5`   | Model for the chat                                         |
| `APP_ID`            | `f1-dashboard`     | Keeps this app's threads apart from others on the same key |
| `OPENF1_PER_MINUTE` | `28`               | OpenF1 request budget per minute                           |
| `ALLOWED_ORIGINS`   | (none)             | Extra origins the API accepts, comma-separated, e.g. a preview domain |

## Pages

| URL                               | What it shows                                    |
| --------------------------------- | ------------------------------------------------ |
| `/`, `/standings`, `/drivers`, `/teams` | Dashboards; picking anything starts a chat |
| `/new`                            | A new chat, with three questions suggested from your earlier ones (`/api/starters`) |
| `/[threadId]`                     | An earlier chat, loaded from Gateway (only in the browser session that made it) |

Each URL is its own page under `src/app/(radio)/`. The layout holds what stays mounted between them: the chat store, the sidebar, the input, and the thread once a conversation has messages. That is what lets the URL move from `/new` (or a dashboard) to the new thread mid-answer without cutting it off.

## How a question is answered

1. The browser sends the thread id and the thread's messages to `/api/chat`; the route uses only the last one, the new question.
2. The route loads the thread's earlier turns from its Gateway conversation, with their tool calls and results.
3. Gateway's Chat Completions API picks F1 tools (`get_results`, `get_lap_times`, `get_standings`, …). The route runs them between completions (`src/lib/tool-loop.ts`) and streams AG-UI events, so each tool call shows its result live.
4. The answer streams back as OpenUI Lang and renders as it arrives, with the F1 component library (`src/library.ts`). The F1 charts take only a session and drivers and fetch their own rows from `/api/f1/[tool]`, so their numbers never pass through the model; tables carry the values the model copies from tool results.
5. The turn is stored in the Gateway conversation before the stream ends, so a follow-up sees it.

## Data

The tools (`src/lib/f1/tools`) call OpenF1 through one rate-limited client with a disk cache under `data/openf1`. Finished sessions are cached forever, and a stale copy is served if OpenF1 is down. `npm run snapshot:f1` fills that cache ahead of time; `npm run snapshot:f1 -- --year 2025 --light` adds last season's races (results, standings and stints only).

Driver, team colour and circuit data for the visuals is committed under `src/assets/f1`. Refresh it for a new season with `npx tsx scripts/snapshot-f1-assets.ts`.

## Deploying

`next.config.ts` bundles `data/**` into the API routes, so run `npm run snapshot:f1` before building. Hosts with a read-only filesystem keep new OpenF1 responses in memory only.

## Visitors and storage

There's no sign-in; it follows the OpenUI docs chat. Each browser tab session makes up an anonymous visitor id (`src/lib/user-id.ts`, kept in sessionStorage) and sends it when asking `/api/frontend-token` for a token. Gateway scopes that token to the id, so a visitor lists and opens only their own threads, which are stored as Gateway conversations. Closing the tab starts a new visitor with an empty list. The id keeps visitors apart; it doesn't prove who anyone is.

The API routes accept only requests from the app's own pages: a request with no `Origin` header (a script, `curl`) is refused, so it can't spend Gateway credit from outside. There's no rate limiting, so add some before promoting the demo widely.
