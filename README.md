# Game Release Tracker

**A desktop app for people who play a lot of games.** It keeps track of the upcoming games from the publishers you follow, keeps a journal of the games you finish, picks something new to play when you can't decide, and turns your year of gaming into a visual recap.

Everything runs on your own computer. There is no account, no cloud and no tracking.

[![CI](https://github.com/hachi23/game-release-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/hachi23/game-release-tracker/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/hachi23/game-release-tracker)](https://github.com/hachi23/game-release-tracker/releases/latest)
![Tests](https://img.shields.io/badge/tests-575%20passing-brightgreen)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

![Upcoming releases, with the next game's artwork filling the screen](docs/screenshots/upcoming.jpg)

## At a glance

| | |
|---|---|
| **What** | A local-first desktop app: syncs release data from a public API (IGDB) into a local database, keeps a personal journal, and turns it into a yearly analytics recap |
| **My role** | Product owner and director: idea, every feature specification, data rules, design decisions, review and testing. Code written by AI coding agents from my specifications ([details below](#my-role-and-how-it-was-built)) |
| **Built with** | Electron, React, TypeScript, Fastify, SQLite, Vitest, GitHub Actions |
| **Quality** | 575 automated tests in 81 files; every change on GitHub runs the tests, builds the app, and starts the packaged app as a new user to open every screen |
| **Shipped** | Public releases with a Windows installer, a Linux `.deb` and an AppImage |
| **Design record** | [6 architecture decision records](docs/adr/) explaining the choices and what each one cost |

---

## My role and how it was built

The idea, the features and every product decision are mine: what the app should do, how each screen should feel, the Year in Review chapters, and the rules for what counts as an upcoming release.

Most of the code was written by AI coding assistants (Anthropic's Claude Code and OpenAI's Codex), working from specifications and plans I wrote. My part of each change:

1. **Specify.** Write what the feature must do, the rules it keeps, and how it should be tested (the domain language and rules are in [CONTEXT.md](CONTEXT.md)).
2. **Direct.** Hand the work to an AI agent with that specification and the repo's [agent guide](AGENTS.md).
3. **Review.** Read the change, run the app, and send it back when it misses the specification.
4. **Verify.** Accept it only when the tests pass and the packaged app works as a new user would see it.
5. **Record.** Write down decisions that shaped the design, with their trade-offs, as [decision records](docs/adr/).

This public repository starts at the first public version (0.6.0), so its commit history is short. The [Changelog](CHANGELOG.md) shows how the app grew.

---

## Try it in two minutes

1. From the [latest release](https://github.com/hachi23/game-release-tracker/releases/latest), download:
   - **Windows**: `Game Release Tracker Setup.exe` (installer) or the `.zip` (no install). Windows may say *"Windows protected your PC"*, because the app isn't signed with a paid certificate. Click **More info**, then **Run anyway**.
   - **Linux Mint or Ubuntu**: the `.deb`, then double-click it to install. It appears in the menu under **Games**. There's also an `.AppImage` that runs without installing.
2. Open it.
3. On the welcome screen, click **Try it with sample data**.

That loads a sample library: 30 upcoming games, 46 finished games with a full Year in Review, and 267 games for the Randomizer. You can look around everything without signing up for anything. **Remove sample data** takes it out again.

![The welcome screen a new user sees](docs/screenshots/welcome.jpg)

---

## What it does

### Upcoming releases
A list of the games coming out from the publishers you follow, grouped by month, with a countdown to the next one. Search it, filter it by genre or platform, mark games as watched or hidden, or add a game by hand. Every game has a detail page with its artwork, screenshots and trailer.

| | |
|---|---|
| ![A game's detail page, tinted by its cover](docs/screenshots/release-detail.jpg) | ![The calendar view](docs/screenshots/calendar.jpg) |
| *A game's page, tinted in its cover's colours* | *The same releases on a calendar* |

### Completed Library
A journal of the games you've finished: when, on what, your rating and your notes. The app finds each game on IGDB (the Internet Game Database) and adds its cover, genres and details automatically.

![The Completed Library](docs/screenshots/completed-library.jpg)

### Year in Review
Your year of gaming told as a story in five chapters: how much you played, what you like, how you rate games, when you play, and your Game of the Year. It can be saved as an image to share. Every chapter is drawn as its own illustrated "realm".

| | |
|---|---|
| ![Year in Review, the overview chapter](docs/screenshots/year-in-review.jpg) | ![Year in Review, Game of the Year](docs/screenshots/year-in-review-goty.jpg) |

### Randomizer
Can't decide what to play? The Randomizer picks a random released game from the whole IGDB catalogue, filtered by genre, theme, platform, rating or year, and avoids repeating recent picks.

![The Randomizer after a spin](docs/screenshots/randomizer.jpg)

### Your own setup
In **Settings** you choose which publishers to follow, which platforms you play on (PC, Xbox, PlayStation, Nintendo Switch) and how far back to track, pick one of twelve colour themes, and set a wallpaper.

![Settings, Sync tab](docs/screenshots/settings-sync.jpg)

---

## Using it with your own games

The sample library is there to look around. To track real releases:

1. Get free API keys from IGDB (it takes about five minutes with a Twitch account: [how to get IGDB keys](https://api-docs.igdb.com/#account-creation)).
2. In the app, open **Settings → API keys**, paste them in and click **Save settings**.
3. In **Settings → Sync**, search for the publishers you follow (or click **Add suggested publishers**) and choose your platforms.
4. Click **Sync now**.

The [User Guide](docs/USER_GUIDE.md) walks through every screen.

---

## Architecture

Three processes, the same shape as many desktop apps:

```mermaid
flowchart LR
    W["Window<br/>React + TypeScript"] -- "HTTP on 127.0.0.1<br/>+ per-launch token" --> E["Engine<br/>Fastify backend"]
    E --> D[("Library<br/>SQLite file")]
    E -- "only when syncing" --> I["IGDB / SteamGridDB<br/>public APIs"]
    S["Desktop shell<br/>Electron"] -. "starts" .-> E
    S -. "opens" .-> W
```

- **The window** only shows screens and asks the engine for data. It never reads or writes files, and saved API keys are never sent back to it.
- **The engine** syncs from IGDB, applies the user's rules, and is the only part that reads or writes the library.
- **The desktop shell** starts both, and handles what only a desktop app can do: file dialogs and encrypting API keys.

[How it works](docs/HOW_IT_WORKS.md) explains this without code; the [Review Guide](docs/REVIEW_GUIDE.md) is a five-minute tour of the source.

## Decisions worth a look

- **Data stays honest.** IGDB stores a game announced for "2027" as December 31, 2027. The app keeps the words ("2027", "Q4 2026") and counts down only to a real announced day ([ADR 5](docs/adr/0005-vague-release-dates-keep-their-words.md)).
- **Syncing never overwrites the user.** Each game is saved on its own, so one bad record leaves the sync "partial" instead of failing it; manual edits win over the data source, and deleted games stay deleted.
- **Only the app can talk to its engine.** The local API refuses requests without a token created at each launch, and turns away requests from web pages ([ADR 2](docs/adr/0002-local-api-answers-only-the-app.md)).
- **Upgrades can't lose data.** Before a new version changes the database layout, it backs up the library; an older version refuses a newer library instead of damaging it.
- **The user decides what to track.** Early versions had one person's taste built in; the public version made publishers, platforms and dates settings ([ADR 6](docs/adr/0006-the-sync-policy-belongs-to-the-user.md)).

---

## Privacy

- **Everything stays on your computer.** Your library, notes and settings live in a local database in your user folder.
- **Your keys are encrypted** with the system's own protection (Windows' data protection, or the login keyring on Linux) and are never shown again after you save them.
- **No accounts, analytics or crash reporting.** The app only contacts:
  - IGDB and Twitch, to look up games (only after you add keys);
  - IGDB's image server, for covers and artwork;
  - SteamGridDB, for extra artwork (only if you add its optional key);
  - YouTube's privacy-enhanced player, only when you press play on a trailer or on theme music.
- **Settings → Diagnostics → Delete all app data** removes everything the app stored.

---

## Documentation

| For | Read |
|---|---|
| Anyone using the app | [User Guide](docs/USER_GUIDE.md) |
| Anyone curious how it works, no coding needed | [How it works](docs/HOW_IT_WORKS.md) |
| What changed in each version | [Changelog](CHANGELOG.md) |
| Why it is built the way it is | [Decision records](docs/adr/) |
| Developers: a guided tour of the code | [Review Guide](docs/REVIEW_GUIDE.md) |
| Developers: where everything lives | [Codebase Map](docs/CODEBASE_MAP.md) |
| Developers: full technical reference | [Technical Documentation](docs/DOCUMENTATION.md) |
| The words the code uses, and the rules it keeps | [CONTEXT.md](CONTEXT.md) |

## Running from source

You need [Node.js](https://nodejs.org) 22.

```bash
npm install
npm test          # 575 automated tests
npm run build     # compile everything
npm run dist      # build the installer and packages for this platform into dist/
npm run smoke     # start the packaged app as a new user and open every screen
```

No API keys are needed to install, test or build. Built with Electron, React, TypeScript, Fastify and SQLite.

## License

[MIT](LICENSE) © hachi23. Game data and images come from [IGDB](https://www.igdb.com) and [SteamGridDB](https://www.steamgriddb.com) and belong to their owners.
