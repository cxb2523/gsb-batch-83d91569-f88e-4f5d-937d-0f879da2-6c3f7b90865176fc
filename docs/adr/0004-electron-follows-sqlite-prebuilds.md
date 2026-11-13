# Electron stays on a version with prebuilt SQLite binaries

`better-sqlite3` is the app's only native module. When a prebuilt binary exists for the Electron version, packaging downloads it; otherwise SQLite must be compiled, which needs Visual Studio build tools on every machine that packages the app, CI included. So Electron moves up only when `better-sqlite3` publishes a prebuild for the new version (currently Electron 42), accepting that the app runs a slightly older Chromium in exchange for builds anyone can reproduce.
