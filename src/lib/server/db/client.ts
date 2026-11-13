import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import type { BaseSQLiteDatabase } from 'drizzle-orm/sqlite-core';
import * as schema from './schema';

// Rutas relativas a jobfilter/: `bun run dev`, `bun run dev:node` y `bun run buscar` corren ahí.
const DB_PATH = resolve('data/jobfilter.db');
const MIGRATIONS = resolve('drizzle');

/** Ambos drivers son síncronos, así que el resto del código usa .all()/.get()/.run() igual. */
export type DB = BaseSQLiteDatabase<'sync', unknown, typeof schema>;

export const runtime = typeof globalThis.Bun !== 'undefined' ? 'bun' : 'node';

async function open(): Promise<DB> {
	mkdirSync(dirname(DB_PATH), { recursive: true });

	if (runtime === 'bun') {
		const { Database } = await import('bun:sqlite');
		const { drizzle } = await import('drizzle-orm/bun-sqlite');
		const { migrate } = await import('drizzle-orm/bun-sqlite/migrator');
		const sqlite = new Database(DB_PATH, { create: true });
		// busy_timeout: la app y la terminal pueden escribir a la vez sin fallar al instante
		sqlite.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;');
		const db = drizzle(sqlite, { schema });
		migrate(db, { migrationsFolder: MIGRATIONS });
		return db as DB;
	}

	// SQLite estándar de Node (better-sqlite3)
	const { default: Database } = await import('better-sqlite3');
	const { drizzle } = await import('drizzle-orm/better-sqlite3');
	const { migrate } = await import('drizzle-orm/better-sqlite3/migrator');
	const sqlite = new Database(DB_PATH);
	sqlite.pragma('journal_mode = WAL');
	sqlite.pragma('foreign_keys = ON');
	const db = drizzle(sqlite, { schema });
	migrate(db, { migrationsFolder: MIGRATIONS });
	return db as DB;
}

export const db = await open();
