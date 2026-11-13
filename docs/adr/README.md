# Decision records

Each record explains one choice that shaped the app, and what it cost.

| # | Decision | In short |
|---|---|---|
| 1 | [A local-first desktop app](0001-local-first-desktop-app.md) | Everything runs on the user's computer: no account, no server, nothing to breach |
| 2 | [The local backend answers only the app](0002-local-api-answers-only-the-app.md) | A per-launch token and a host check keep other programs and web pages out of the local API |
| 3 | [The Completed Library lives in the app](0003-completed-library-lives-in-the-app.md) | The journal moved out of a spreadsheet so there is one place to edit each game |
| 4 | [Electron follows SQLite's prebuilt binaries](0004-electron-follows-sqlite-prebuilds.md) | Builds stay reproducible on any machine, at the cost of a slightly older Chromium |
| 5 | [Vague release dates keep their words](0005-vague-release-dates-keep-their-words.md) | "Q4 2026" stays "Q4 2026"; only a real announced day gets a countdown |
| 6 | [The sync policy belongs to the user](0006-the-sync-policy-belongs-to-the-user.md) | Publishers, platforms and dates are settings, not one person's taste built in |
