# Runtime storage

The runtime modules own app-data locations and filesystem operations that must work across development and packaged desktop modes.

- `layout.ts` — resolves writable data directories, explicit restore input, and legacy locations.
- `wallpaperStorage.ts` — stores, reads, and clears the current wallpaper.

Keep database, HTTP, Electron, and React concerns at their owning seams. Runtime storage is for files, paths, and restore behaviour.
