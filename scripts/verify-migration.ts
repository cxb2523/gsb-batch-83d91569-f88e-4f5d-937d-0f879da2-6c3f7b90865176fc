// Verificación de migración incremental sobre una base con solo el esquema 0001.
import { Database } from 'bun:sqlite';
import { readFileSync, rmSync } from 'node:fs';

const PATH = 'data/mig-check.db';
for (const ext of ['', '-wal', '-shm']) rmSync(PATH + ext, { force: true });

// 1. base "vieja": migraciones 0000 y 0001 ya aplicadas, con el registro de drizzle tal como
// queda en una base real (la columna hash la deja el migratorio; aquí basta con el formato).
const sqlite = new Database(PATH);
for (const f of ['drizzle/0000_init.sql', 'drizzle/0001_cache_y_cursores.sql']) {
	const sql = readFileSync(f, 'utf8').split('--> statement-breakpoint').join('');
	sqlite.exec(sql);
}
sqlite.exec("INSERT INTO keywords (term, enabled, source, created_at) VALUES ('python', 1, 'manual', '2026-01-01')");
// el migrador de drizzle compara el created_at del último registro con el folderMillis de
// cada migración (valor "when" del journal): con las dos primeras ya registradas con su
// marca real, solo la 0002 (más nueva) debe ejecutarse
sqlite.exec('CREATE TABLE IF NOT EXISTS __drizzle_migrations (id integer primary key autoincrement, hash text not null, created_at numeric not null)');
sqlite.exec(
	"INSERT INTO __drizzle_migrations (hash, created_at) VALUES ('manual-0000', 1792024518610), ('manual-0001', 1792255194343)"
);
sqlite.close();

// 2. abrir con el cliente real: debe aplicar 0002 sin borrar lo existente
process.env.JOBFILTER_DB = PATH;
const { db } = await import('../src/lib/server/db/client.ts');
const tables = db.all("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").map((r: any) => r.name);
const keyword = db.all('SELECT term FROM keywords');
const logCols = db.all('PRAGMA table_info(search_page_logs)').map((r: any) => r.name);

console.log('tablas:', tables.join(','));
console.log('keyword conservada:', JSON.stringify(keyword));
console.log('columnas search_page_logs:', logCols.join(','));

if (!tables.includes('search_page_logs')) throw new Error('FALLO: no se creó search_page_logs');
if (keyword.length !== 1 || keyword[0].term !== 'python') throw new Error('FALLO: se perdió la keyword');
console.log('OK: migración incremental conserva datos y crea la bitácora');

// 3. la base es temporal: se intenta borrar al terminar. En Windows el driver puede mantener
// el archivo tomado hasta que el proceso muere; data/ está en .gitignore y la próxima
// ejecución lo limpia al arrancar, así que un fallo de borrado no debe tumbar el script.
try {
	for (const ext of ['', '-wal', '-shm']) rmSync(PATH + ext, { force: true });
} catch (err) {
	console.warn('Aviso: no se pudo borrar la base temporal (seguirá en data/, ignorada por git):', String(err));
}
