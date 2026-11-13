# Changelog

What changed in each version, in plain language.

## 0.7.0

**Watchlist**
- **☆ Watch** on the featured game or a game's page adds it to your watchlist. Watched games show a ★ in the Upcoming list, and **More filters → Watched only** lists just them.

**Delays at a glance**
- When a sync finds a game's date has moved, its row and the featured panel say **Delayed from Mar 14, 2027** (or **Moved up from …**). A game's page shows its full **Date history**, including when a vague date such as "2027" becomes a real day. The history starts with your first sync after updating.

**Alerts for watched games**
- A system notification tells you when a watched game comes out today, or when a sync finds it delayed, moved up or given a real date (only changes made after you started watching). Click it to open the game. Where Windows won't show the app's notifications (the zip version), they appear as a tray balloon. Turn them off in **Settings → Sync**.
- With **Sync automatically** on, the app also syncs every 12 hours while it stays open, so alerts reach you while it waits in the tray.

**Start with Windows**
- **Settings → Sync → Start with Windows, in the tray** starts the app when you log in, waiting in the tray so syncs and alerts keep coming. On Linux it's **Start when I log in, in the tray** and works through the desktop's autostart folder.

**Minimize to tray**
- Minimizing the window now hides it to a Game Release Tracker icon in the system tray (the notification area on Windows). Click the icon, or choose **Open Game Release Tracker** from its menu, to bring the window back; **Quit** in the same menu closes the app. The close button still quits.
- Starting the app again while it is in the tray brings the window back. On Linux desktops that don't show tray icons (GNOME without an AppIndicator extension), that is the way back.

**Fixes**
- Changing a game's date by hand to a vague one ("2028", "Q4 2027") without clearing its old day now drops that day, so the game sorts and counts down by the date you typed. Before, it kept using the old day until the next sync.
- Automatic sync now waits the full 12 hours in every time zone. Before, it read the last sync's time as local time, so ahead of UTC it synced early and behind UTC it waited too long.

**Your library**
- The first start upgrades your library to keep date history and alerts (schema v21). A backup is made first, as with every upgrade; after it, older versions of the app can't open the library.

## 0.6.3

**Fixes**
- In January, the sample library shows all 30 upcoming games. Before, its first games were dated last December and the default "from January 1" filter hid them.

## 0.6.2

**Fixes**
- A game announced only for a year, quarter or month ("2027", "Q4 2026", "Dec 2026") shows those words instead of a made-up countdown like "Arrives in 461 days", and no longer appears on the calendar on December 31. The next sync corrects games already in your list.
- In Completed Library, the filters scroll inside their panel at small window sizes, so **Add completed game** is always on screen.
- A cover or artwork that can't load (for example offline) leaves an empty frame instead of a broken-image icon.

**Nicer first run**
- The welcome screen shows what each part of the app does, beside the two ways to start.
- The sample library's upcoming list now starts last month, with a game or two just out and the rest still to come, instead of a year of already-released games.

**Linux**
- Linux Mint and Ubuntu users can install the app from a `.deb` (it appears under **Games** in the menu), or run the AppImage without installing. Both are started as a new user and clicked through before each release.

**Safer builds**
- The packaged app turns off Electron features it never uses (running as plain Node, Node options from the environment, debugger flags), so it can't be repurposed through them.
- Every change on GitHub now builds the app, starts it as a new user and opens every screen; releases do the same on Windows before the installer is published.

## 0.6.1

**Try the Randomizer without an account.** With the sample library loaded and no IGDB keys saved, the Randomizer now spins among 267 real games that come with the app. Genre, theme, game mode, platform, rating and year filters all work; the filters that search all of IGDB (tags, quick picks, series, similar games, camera view) say they need your own keys.

**Its own data folder.** The app keeps its data in `%APPDATA%\Game Release Tracker`, so it never shares a library with another build.

## 0.6.0

The first public version.

**Your own sync settings.** A new **Sync** tab in Settings: search IGDB for the publishers you follow (or add a suggested set), choose your platforms (PC, Xbox, PlayStation, Nintendo Switch), set how far back to track releases, and turn automatic syncing on or off. These replace rules that used to be built in.

**A new welcome and a sample library.** A first-time user can load a sample library (30 upcoming games and 46 finished games with a full Year in Review) and look around every screen without IGDB keys. **Remove sample data** takes it out again.

**Settings in tabs:** Appearance, API keys, Sync and Diagnostics.

**Privacy.**
- Automatic sync is off until you turn it on.
- Year in Review's theme music waits for a click, unless you choose autoplay in Settings → Appearance.
- The installed app only uses keys saved in Settings, never ones from the computer's environment.
- **Delete all app data** in Settings → Diagnostics removes everything the app stored, after asking.
- **Open log folder** in Settings → Diagnostics.

**A Windows installer** alongside the zip, built automatically on GitHub for every release.

## 0.5.0

A clean-up release.

**Fixes**
- Clearing a game's exact finish date and typing a month no longer loses the month.
- A game's rating text and score can no longer disagree.
- The Upcoming list now refreshes after a sync that partly failed.
- A sync cut off by closing the app no longer leaves the app waiting for it forever.
- The Year in Review poster always draws in the right fonts.
- Keyboard shortcuts and Tab work while Year in Review's intro plays.

**Faster and smaller**
- Settings like Randomizer filters now survive restarting the app.
- The download is 11 MB smaller, the app ships 68 files instead of about 1,500, and the engine starts faster.
- The Completed Library and Settings load when you first open them, not at startup.
- Blurred backgrounds use smaller images.

## Before 0.5

The app grew from an upcoming-releases list into the full journal: the Calendar, the Completed Library with IGDB matching, the Randomizer, and Year in Review with its five illustrated chapters, theme music and shareable posters.
