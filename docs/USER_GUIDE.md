# User Guide

How to use Game Release Tracker, screen by screen. No technical knowledge needed.

**Contents:** [Getting started](#getting-started) · [Upcoming](#upcoming) · [Calendar](#calendar) · [Completed Library](#completed-library) · [Randomizer](#randomizer) · [Year in Review](#year-in-review) · [Settings](#settings) · [Your data](#your-data) · [If something goes wrong](#if-something-goes-wrong) · [Common questions](#common-questions)

---

## Getting started

### Install
From the [latest release](https://github.com/hachi23/game-release-tracker/releases/latest), download either:
- **`Game Release Tracker Setup.exe`**: installs the app like any other program, or
- **the `.zip`**: extract it anywhere and run `Game Release Tracker.exe`. Nothing is installed.

Windows may show *"Windows protected your PC"*. That appears for apps that aren't signed with a paid certificate. Click **More info**, then **Run anyway**.

On **Linux Mint or Ubuntu**, download the `.deb` and double-click it (or run `sudo apt install ./game-release-tracker_*.deb`). Game Release Tracker then appears in the menu under **Games**. The `.AppImage` runs without installing: make it executable (right-click → Properties → Permissions, or `chmod +x`) and open it. If the AppImage won't start, use the `.deb`.

### First look: the sample library
A new install has nothing in it, so the app offers two choices:

- **Try it with sample data** loads a ready-made library, so you can see every screen straight away: 30 upcoming games, 46 finished games (with a full Year in Review for last year) and 267 games for the Randomizer. The games are real; the ratings, dates, platforms and notes are made up. Upcoming dates are moved so the list starts last month (this month in January): a game or two just out, and the rest still to come.
- **Set up my own** takes you to the settings you need for your own games (below).

While the sample is loaded, Upcoming shows a note with a **Remove sample data** button. Removing it takes out exactly the sample games and leaves anything you added yourself.

### Setting up your own games
The app gets its game information from **IGDB**, the Internet Game Database. IGDB is free, but it needs your own keys:

1. Follow [IGDB's guide](https://api-docs.igdb.com/#account-creation): log in with a Twitch account, register an application, and copy its **Client ID** and **Client Secret**. It takes about five minutes.
2. In the app, open **Settings → API keys**, paste both in, and click **Save settings**. **Test credentials** checks that they work.
3. Optional: a free [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api) key fills in artwork IGDB doesn't have.
4. Open **Settings → Sync** and choose what to track (see [Sync](#sync)).
5. Click **Sync now** in the top right corner.

---

## Upcoming

Games coming out from the publishers you follow, grouped by month.

- **Click** a game to feature it: its artwork fills the screen with a countdown ("Arrives in 5 days"). A game with only a month, quarter or year announced shows just that ("Dec 2026", "Q4 2026", "2027") instead of a countdown, and stays off the calendar until it has a day.
- **Double-click** it, press **Enter**, or click **Open details** for its full page: artwork, screenshots, trailer, dates, platforms and publisher. Every detail page takes on the colours of the game's cover.
- **Search** by title, publisher or keyword, and filter by **Genre**. **More filters** narrows by publisher, platform, category or date precision, can show games you've hidden or marked as released, and can show only the games you watch.
- **☆ Watch** (on the featured game or a game's page) adds a game to your watchlist; it then shows a ★ in the list. **More filters → Watched only** shows just your watched games. Click **★ Watching** to stop watching.
- When a sync finds a new date for a game, its row says **Delayed from …** or **Moved up from …**. The game's page lists every change under **Date history**, including a vague date becoming exact ("Date announced").
- **Add game** adds one by hand. You can search IGDB for it or type the details yourself.
- Tick several games to delete them together.

On a game's page:
- **Edit title** and **Edit details** change anything about it. Your edits are kept even when the next sync brings new information from IGDB.
- **Add artwork** uses your own image; artwork can be reordered or removed.
- **Play trailer** loads the trailer only when you press it.
- **Delete** removes the game. **Delete + block** also stops the next sync from bringing it back.

### Sync
**Sync now** asks IGDB for every upcoming game by your tracked publishers and updates what's already there. It adds new games, updates changed dates and artwork, and skips games you blocked. If a few games fail to save, the rest are kept and the result says **partial**.

---

## Calendar

The same upcoming games on a month grid. Use **‹** and **›** to change month, **Today** to come back, and click a game to open it.

---

## Completed Library

A journal of the games you've finished.

- Games are grouped by the month you finished them. Ratings of 9 or higher get a gold frame.
- **Grouped** and **Grid** switch between the two layouts. Filters on the left narrow by platform, genre, year, month, minimum rating or whether a game has a date.
- **Add completed game**: search IGDB for the game, then add your rating (for example `8.5/10`), the date you finished it (a full date, a month or just a year) and notes.
- The app matches each game to IGDB for its cover, screenshots, genres and critic score. If it picked the wrong game, open the game and click **Fix match** to choose the right one. A game marked **IGDB match needs review** is one where it wasn't sure.
- Everything on a game's page can be edited later.

---

## Randomizer

For when you can't decide what to play. Set filters on the left if you like, then press **Spin**. A reel of covers spins, slows down and stops on one game, which opens into a card with its cover, year, genres, platforms, IGDB rating and summary.

Filters:
- **Quick picks**: JRPG, Anime, or Made in Japan (by a Japanese studio).
- **Platforms**: any PlayStation, Xbox, Nintendo or PC. Only games on these are suggested.
- **Genres, themes and tags** to include or exclude. Any IGDB tag can be found by name.
- **Game modes** (single player, co-op and so on) and **camera view** (first person, side view and so on).
- **Series** (for example Final Fantasy or Persona) and **Similar to** a game you name. **More like this** on a pick does the same for that game.
- **Rating** and **number of ratings** ranges, and **release years**. Most IGDB games have no rating yet, so they're left out unless you tick **Include unrated games**.
- Games in your Completed Library are left out by default; games in Upcoming can be too.

**Spin again** gives another game. The same game never comes up twice in a row, and your last 50 picks are skipped. **Recent picks** shows them; **Clear history** starts fresh. If nothing matches, the app says why.

**With the sample library and no keys**, spins pick from its 267 games and the genre, theme, mode, platform, rating and year filters still work. Tags, quick picks, series, similar games and camera view search all of IGDB, so they need your own keys.

---

## Year in Review

Your year of gaming as a story in five chapters. It fills the whole window and opens with a short intro (click or press any key to skip). Choose a year at the top right; the current year is marked "so far". **Escape** or **✕ Leave** goes back.

| Chapter | What it shows |
|---|---|
| **Overview** (a sea chart) | How many games, your busiest month, average rating, your first and last finish |
| **Taste** (a spellbook) | Top genres and themes, platforms, favourite developer, solo or together, something new you tried |
| **Ratings** (a forge) | Your "player type", how your ratings spread, a hot take where you and the critics disagreed, a hidden gem |
| **Timing & Habits** (an astrolabe) | Day-one finishes, the game you were latest to, oldest and newest games, your longest monthly streak |
| **Game of the Year** (the throne) | Your top game over its own artwork, with your note and the rest of your year below it |

- Move between chapters with the tabs, the **←** and **→** keys, or by scrolling past the end of a chapter.
- Click any game to open its page; **← back to Year in Review** returns you to the same spot.
- Click a month, a rating bar, a genre, a platform or "rated 9 or higher" to see those games.
- **Choose my GOTY** picks a different Game of the Year; **Use automatic pick** goes back to your highest-rated game.
- **Set theme music** takes a YouTube link for the game's music. **▶ Play theme** plays it in the background while you look around. To have it start by itself, turn it on in **Settings → Appearance**.
- **Save as image** makes a poster of every game you finished that year, **Horizontal** for a screen or **Vertical** for a phone, and asks where to save it.

A game needs a finish date to count. Games with only a year count in the totals but not in the monthly charts. Each chapter says at the bottom how many games it couldn't use.

---

## Settings

Settings has four tabs. It opens on **API keys** while your keys need attention.

**Appearance**: twelve colour themes, a wallpaper (used behind lists and on Upcoming when a game has no artwork), and whether Year in Review's theme music starts by itself.

**API keys**: your IGDB and SteamGridDB keys. Once saved, a key is only ever shown as "saved"; **Clear credentials** removes them.

**Sync**: what Sync looks for.
- **Publishers**: search IGDB for a company and click **Add**, or click **Add suggested publishers** for a starter set. A game counts when a tracked company published or developed it. **×** stops tracking one.
- **Platforms**: PC, Xbox, PlayStation and Nintendo Switch. At least one stays on.
- **Track releases from**: the earliest release date to show. It starts at 1 January of the current year.
- **Sync automatically**: off by default. When on, the app syncs at startup if the last sync was over 12 hours ago, and again every 12 hours while it stays open (in the tray, for example).
- **Notify me when a watched game comes out or its date changes**: on by default. The app shows a system notification on a watched game's release day, and when a sync finds a new date for one. Click the notification to open the game. Notifications only come while the app is running (it can wait in the tray), and only for date changes made after you started watching. On Windows, if the system won't show the app's notifications (for example the zip version), the tray icon shows them as a small balloon instead.
- **Start with Windows, in the tray** (on Linux: **Start when I log in**): off by default. When on, the app starts when you log in and waits in the tray, so syncs and alerts keep coming without opening it. Shown in the app you download (installer, zip or AppImage), not when running from source code. It starts the app from where it is now: if you move the zip folder or the AppImage, turn the switch off and on again.

**Diagnostics**: where the app's log file is, with buttons to open the log or its folder. **Delete all app data** removes your library, covers, wallpaper, saved keys, backups and logs from this computer and restarts the app as a new install. It asks you to confirm first.

---

## Your data

- Everything is stored on your computer, in `%APPDATA%\Game Release Tracker` on Windows or `~/.config/Game Release Tracker` on Linux.
- Your API keys are encrypted using the system's own protection: Windows' data protection, or the login keyring on Linux (on a Linux desktop without a keyring they are stored unencrypted).
- Before the app upgrades your library to a new version, it saves a backup copy in a `backups` folder next to it (the last three are kept).
- Updating the app never touches your data.
- There are no accounts, analytics or crash reports. The app only contacts IGDB (and Twitch for its login), IGDB's image server, SteamGridDB if you added its key, and YouTube's privacy-enhanced player when you play a trailer or theme music.

---

## If something goes wrong

- The app shows a short message about what failed. The details go to a log file: open it from **Settings → Diagnostics**. Keys and other secrets are removed before anything is written to it.
- If a screen crashes, the app shows **Something went wrong** with a **Reload** button.
- If Sync says it needs publishers, add some in **Settings → Sync**.
- If Sync fails with a message about keys, check them in **Settings → API keys** with **Test credentials**.

---

## Common questions

**Do I need an internet connection?**
Only to sync, search IGDB, spin the Randomizer and load artwork the first time. Covers shown on game pages are saved, so your library works offline. A cover that was never loaded shows as an empty frame until you are back online.

**Will I lose my data if I update the app?**
No. Your data lives separately from the program, and a backup is made before any upgrade.

**Can I use it on a Mac or Linux?**
Releases are built for Windows and for Linux (a `.deb` for Linux Mint, Ubuntu and Debian, and an AppImage for other distributions), and each is tested before release. There's no Mac build; the code runs on macOS from source, but it isn't tested there.

**Where does the window go when I minimize it?**
To the system tray: look for the app's icon in the notification area (on Windows, it may be under the **^** arrow by the clock). Click it, or right-click and choose **Open Game Release Tracker**, to bring the window back. Right-click → **Quit** closes the app; so does the window's close button. On Linux desktops that don't show tray icons, start the app again from the menu and the same window comes back.

**Why does a game say "IGDB match needs review"?**
The app wasn't sure it matched the right IGDB game. Check its cover and details, and use **Fix match** if they're wrong.

**Can the Randomizer show the same game again?**
Not straight away: your last 50 picks are skipped. If your filters are so narrow that nothing else is left, it says you've seen most of them. **Clear history** starts fresh.

**Why is a Year in Review card missing?**
A card only shows when it has something to say. The hot take, for example, needs a game where your rating and the critics' differ by 15 points or more.

**Why does the app look like this?**
The style is inspired by "HD-2D" games like *Octopath Traveler*: framed panels with corner ornaments over game artwork. Abyss Gold is the default theme; eleven others are in **Settings → Appearance**.
