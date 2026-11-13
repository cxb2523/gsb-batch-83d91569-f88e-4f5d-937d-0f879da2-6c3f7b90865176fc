import { sql } from 'drizzle-orm';
import { check, index, integer, primaryKey, sqliteTable, text, unique } from 'drizzle-orm/sqlite-core';

export const companies = sqliteTable(
	'companies',
	{
		id: integer('id').primaryKey(),
		name: text('name').notNull(),
		normalizedName: text('normalized_name').notNull().unique(),
		list: text('list', { enum: ['negra', 'blanca'] }),
		/** JSON con los motivos (ver features/companies/reasons.ts). */
		listReason: text('list_reason'),
		listSource: text('list_source', { enum: ['auto', 'manual'] }),
		listedAt: text('listed_at')
	},
	(t) => [
		check('companies_list_check', sql`${t.list} IN ('negra', 'blanca')`),
		check('companies_list_source_check', sql`${t.listSource} IN ('auto', 'manual')`)
	]
);

export const postings = sqliteTable(
	'postings',
	{
		id: integer('id').primaryKey(),
		platform: text('platform').notNull(),
		externalId: text('external_id').notNull(),
		url: text('url').notNull(),
		title: text('title').notNull(),
		normalizedTitle: text('normalized_title').notNull(),
		companyId: integer('company_id').references(() => companies.id),
		recruiter: text('recruiter'),
		location: text('location'),
		modality: text('modality'),
		description: text('description'),
		descriptionHash: text('description_hash'),
		publishedAt: text('published_at').notNull(),
		publishedRaw: text('published_raw'),
		firstSeenAt: text('first_seen_at').notNull(),
		lastSeenAt: text('last_seen_at').notNull(),
		status: text('status', { enum: ['nueva', 'aplicada', 'descartada'] })
			.notNull()
			.default('nueva'),
		statusAt: text('status_at'),
		/** Publicaciones de esta misma vacante; lo calcula recalculateBlacklist. */
		repeatTimes: integer('repeat_times').notNull().default(1),
		repeatFirst: text('repeat_first')
	},
	(t) => [
		unique('postings_platform_external_id_unique').on(t.platform, t.externalId),
		index('postings_by_status').on(t.status, t.publishedAt),
		index('postings_by_company').on(t.companyId, t.normalizedTitle),
		check('postings_status_check', sql`${t.status} IN ('nueva', 'aplicada', 'descartada')`)
	]
);

/** Cada fecha de publicación distinta de una misma vacante (para detectar republicaciones). */
export const publications = sqliteTable(
	'publications',
	{
		postingId: integer('posting_id')
			.notNull()
			.references(() => postings.id),
		publishedAt: text('published_at').notNull()
	},
	(t) => [primaryKey({ columns: [t.postingId, t.publishedAt] })]
);

export const keywords = sqliteTable(
	'keywords',
	{
		id: integer('id').primaryKey(),
		term: text('term').notNull().unique(),
		enabled: integer('enabled', { mode: 'boolean' }).notNull().default(true),
		/** 'claude' = viene de profile/keywords.json; 'manual' = agregada desde la app. */
		source: text('source', { enum: ['claude', 'manual'] }).notNull(),
		createdAt: text('created_at').notNull()
	},
	(t) => [check('keywords_source_check', sql`${t.source} IN ('claude', 'manual')`)]
);

export const runs = sqliteTable('runs', {
	id: integer('id').primaryKey(),
	platform: text('platform').notNull(),
	startedAt: text('started_at').notNull(),
	finishedAt: text('finished_at'),
	found: integer('found').notNull().default(0),
	new: integer('new').notNull().default(0),
	error: text('error')
});

export const platforms = sqliteTable('platforms', {
	id: text('id').primaryKey(),
	pausedUntil: text('paused_until'),
	failures: integer('failures').notNull().default(0)
});

/**
 * Detalle ya pedido de cada vacante, aunque se haya descartado (idioma, relevancia): así no
 * se vuelve a pedir en cada búsqueda.
 */
export const detailCache = sqliteTable(
	'detail_cache',
	{
		platform: text('platform').notNull(),
		externalId: text('external_id').notNull(),
		description: text('description'),
		fetchedAt: text('fetched_at').notNull()
	},
	(t) => [primaryKey({ columns: [t.platform, t.externalId] })]
);

/**
 * Hasta cuándo se buscó completa cada palabra clave en cada plataforma. Cada palabra avanza
 * por su cuenta: si una búsqueda se corta por el cupo de peticiones, las que faltaron siguen
 * en la próxima desde donde quedaron.
 */
export const keywordCursors = sqliteTable(
	'keyword_cursors',
	{
		platform: text('platform').notNull(),
		term: text('term').notNull(),
		searchedAt: text('searched_at').notNull()
	},
	(t) => [primaryKey({ columns: [t.platform, t.term] })]
);
