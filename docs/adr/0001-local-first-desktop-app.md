# A local-first desktop app, with no account and no server

The app is a personal journal, so it runs entirely on the user's computer: an Electron window, a local backend in a child process, and a SQLite database in the user's data folder. There is no account, no cloud copy and no analytics. This means no sign-up, no running costs and nothing of the user's to breach, at the price of no sync between devices and a download for each platform instead of a website. The only network calls go to the services that supply game data (IGDB, SteamGridDB) and to YouTube when the user presses play.
