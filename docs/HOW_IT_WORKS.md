# How it works

What happens inside Game Release Tracker, and why it was built this way, explained without code. For the technical version, see the [Technical Documentation](DOCUMENTATION.md).

---

## The big picture

The app is three programs working together on your computer, the same way many desktop apps (Slack, Spotify, Visual Studio Code) are built:

```text
  ┌───────────────────────────┐
  │  The window you see       │  shows the screens, reacts to clicks
  └─────────────┬─────────────┘
                │ asks for data
  ┌─────────────▼─────────────┐
  │  The engine               │  finds games, applies your rules,
  │  (runs in the background) │  saves everything
  └──────┬──────────────┬─────┘
         │              │
  ┌──────▼──────┐  ┌────▼──────────────────┐
  │ Your library │  │ IGDB, on the internet │
  │ (one file)   │  │ (only when needed)    │
  └──────────────┘  └───────────────────────┘

  The desktop shell looks after both: it starts the engine, opens the
  window, and handles anything that touches your computer (files, dialogs).
```

- **The window** is what you click on. It never touches your files or the internet directly; it asks the engine.
- **The engine** does the real work: it talks to IGDB, applies your sync settings, and reads and writes your library.
- **The desktop shell** starts the engine, opens the window, and handles things only a desktop app can do, like save dialogs and keeping your keys encrypted.

Keeping these apart means a problem in one doesn't take down the others, and the part that holds your keys and files is never the part that shows web content.

---

## Where the information comes from

| What | Where from |
|---|---|
| Upcoming games, their dates, publishers and platforms | IGDB, the Internet Game Database (run by Twitch) |
| Covers, artwork and screenshots | IGDB's image server, plus SteamGridDB for missing artwork |
| Trailers and theme music | YouTube, only when you press play |
| Your ratings, notes and finish dates | You |

Your library is a single database file on your computer. Nothing is uploaded anywhere.

---

## What happens when you press "Sync now"

1. **Ask.** The engine asks IGDB for every game your tracked publishers are credited on, from your "track releases from" date onwards.
2. **Sort.** Each game goes through your rules: is it on one of your platforms? Is it a real release rather than a demo, season pass or deluxe edition? Is it by a publisher or studio you follow?
3. **Fill in.** For games with no artwork, it asks SteamGridDB.
4. **Save, one game at a time.** Each game is saved separately, so one bad entry can't spoil the rest: the sync finishes and says **partial**.
5. **Respect your changes.** If you edited a game's title or date by hand, your edit wins over IGDB's. Games you deleted and blocked never come back.
6. **Note what moved.** When a game's date is different from last time, the engine writes down the change: delayed, moved up, or a vague date ("2027") becoming a real day. It compares the stretch of time each date means, so "2027" turning into "March 14, 2027" counts as the date being announced, not a delay. That history is what the "Delayed from" badge and the alerts read.

---

## How your data is kept safe

- **Backups before upgrades.** When a new version of the app changes how the library is stored, it first copies your library to a `backups` folder.
- **Never opened by a newer or older app by mistake.** A library records which version of the storage format it uses, and an older app refuses a newer library instead of damaging it.
- **Your keys are encrypted** with the system's own protection (Windows' data protection, or the login keyring on Linux) before they're stored, and never shown again.
- **Only this app can use its engine.** The engine only answers requests from the app's own window, which carries a secret that changes every launch; other programs and websites are turned away.
- **Links open in your browser,** never inside the app, so the app window only ever shows the app.

---

## Decisions behind the design

**Local-first, no account.** A personal game journal doesn't need a server. Keeping everything on your computer means no sign-up, no monthly cost, nothing to breach, and your library, ratings and notes keep working offline. Artwork loads from IGDB the first time; offline, a cover that was never saved shows as an empty frame rather than an error.

**You choose what to track.** Early versions had one person's taste built in: a fixed list of publishers, PC and Xbox only, and no sports games. The public version turns those into settings, so a new user starts with nothing tracked and picks their own publishers and platforms.

**A sample library for trying it out.** The app needs free IGDB keys to find games, and setting those up takes a few minutes. So a first-time user can load a sample library instead and see every screen straight away, including a Randomizer that spins among 267 bundled games.

**Privacy by default.** Automatic syncing is off until you turn it on. YouTube only loads when you press play. There's no analytics or crash reporting, and one button deletes everything the app stored.

**It keeps watch, quietly.** Minimizing tucks the app into the tray instead of closing it, and it can start there when you log in. While it waits it can sync every 12 hours and tell you, with an ordinary system notification, when a game you watch comes out or changes date. Each alert shows once, only for games you chose to watch, and never for a change that happened before you started watching. All of this is your choice: auto-sync starts off, and alerts and starting at login each have their own switch.

**Honest dates.** IGDB stores a game announced for "2027" as December 31, 2027. The app keeps the words ("2027", "Q4 2026") and only counts down to a real day, so it never promises a date nobody has announced.

**A look of its own.** The style borrows from "HD-2D" games like *Octopath Traveler*: framed panels with corner ornaments over game artwork. Year in Review gives each chapter its own illustrated world: a sea chart, a spellbook, a forge, an astrolabe and a throne room.

---

## How quality is checked

- **575 automated tests** check the app's behaviour: that edits survive a sync, that a crashed sync is cleaned up, that the Randomizer never repeats a recent pick, that the sample library can be removed without touching your own games, and much more.
- **Every change is checked automatically** on GitHub: the tests run, the whole app is built, and a packaged copy is started and clicked through (below).
- **Every release is built automatically.** Tagging a version on GitHub builds the Windows installer and zip on a clean machine.
- **Packaged builds are tested for real**: `npm run smoke` starts the packaged app with an empty profile, loads the sample library, opens every screen, closes it, and fails on any error on the page or in the app's log. GitHub runs it on a Linux build for every change and on the Windows build before every release.

---

## Words you might see

| Word | Meaning |
|---|---|
| **IGDB** | The Internet Game Database: the public source of game information, like IMDb for games |
| **API key** | A password that lets a program use an online service; you get your own free IGDB keys |
| **Sync** | Asking IGDB for new and changed games and updating your list |
| **Tracked publisher** | A company whose games you want to hear about |
| **Release** | An upcoming game in your list |
| **Completed game** | A game in your journal of finished games |
| **Match** | Linking a game you entered to its IGDB entry, to get its cover and details |
| **Block** | Deleting a game so sync never brings it back |
| **Sample library** | The ready-made library for trying the app without keys |
