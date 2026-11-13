import { afterEach, describe, expect, test } from "vitest";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import Database from "better-sqlite3";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "grt-migrate-"));
  dirs.push(dir);
  return dir;
}

const version = (db: Database.Database) => (db.prepare("select version from schema_version").get() as { version: number }).version;
const backupsIn = (dir: string) => (existsSync(join(dir, "backups")) ? readdirSync(join(dir, "backups")) : []);

describe("migration safety", () => {
  test("upgrading an existing library backs it up first, and the backup holds the old version", () => {
    const dir = tempDir();
    const db = openDatabase(join(dir, "tracker.db"));
    runMigrations(db);
    db.prepare("update schema_version set version = 15").run();

    runMigrations(db);

    expect(version(db)).toBeGreaterThan(15);
    const backups = backupsIn(dir);
    expect(backups).toHaveLength(1);
    expect(backups[0]).toMatch(/^tracker\.v15\..+\.db$/);
    const backup = new Database(join(dir, "backups", backups[0]), { readonly: true });
    expect(version(backup)).toBe(15);
    backup.close();
    db.close();
  });

  test("a new or already up-to-date library is not backed up", () => {
    const dir = tempDir();
    const db = openDatabase(join(dir, "tracker.db"));

    runMigrations(db);
    runMigrations(db);

    expect(backupsIn(dir)).toEqual([]);
    db.close();
  });

  test("only the three most recent backups are kept", () => {
    const dir = tempDir();
    const db = openDatabase(join(dir, "tracker.db"));
    runMigrations(db);
    for (let run = 0; run < 5; run++) {
      db.prepare("update schema_version set version = 15").run();
      runMigrations(db);
    }

    expect(backupsIn(dir)).toHaveLength(3);
    db.close();
  });

  test("a library from a newer app version is refused and left untouched", () => {
    const dir = tempDir();
    const db = openDatabase(join(dir, "tracker.db"));
    runMigrations(db);
    db.prepare("update schema_version set version = 999").run();

    expect(() => runMigrations(db)).toThrow(/newer version of Game Release Tracker/);
    expect(version(db)).toBe(999);
    db.close();
  });
});
