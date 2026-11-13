-- Editada a mano: IF NOT EXISTS para adoptar la base creada antes de usar Drizzle sin perder datos.

CREATE TABLE IF NOT EXISTS `companies` (
	`id` integer PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`normalized_name` text NOT NULL,
	`list` text,
	`list_reason` text,
	`list_source` text,
	`listed_at` text,
	CONSTRAINT "companies_list_check" CHECK("companies"."list" IN ('negra', 'blanca')),
	CONSTRAINT "companies_list_source_check" CHECK("companies"."list_source" IN ('auto', 'manual'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS `companies_normalized_name_unique` ON `companies` (`normalized_name`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `keywords` (
	`id` integer PRIMARY KEY NOT NULL,
	`term` text NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`source` text NOT NULL,
	`created_at` text NOT NULL,
	CONSTRAINT "keywords_source_check" CHECK("keywords"."source" IN ('claude', 'manual'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS `keywords_term_unique` ON `keywords` (`term`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `platforms` (
	`id` text PRIMARY KEY NOT NULL,
	`paused_until` text,
	`failures` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `postings` (
	`id` integer PRIMARY KEY NOT NULL,
	`platform` text NOT NULL,
	`external_id` text NOT NULL,
	`url` text NOT NULL,
	`title` text NOT NULL,
	`normalized_title` text NOT NULL,
	`company_id` integer,
	`recruiter` text,
	`location` text,
	`modality` text,
	`description` text,
	`description_hash` text,
	`published_at` text NOT NULL,
	`published_raw` text,
	`first_seen_at` text NOT NULL,
	`last_seen_at` text NOT NULL,
	`status` text DEFAULT 'nueva' NOT NULL,
	`status_at` text,
	`repeat_times` integer DEFAULT 1 NOT NULL,
	`repeat_first` text,
	FOREIGN KEY (`company_id`) REFERENCES `companies`(`id`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "postings_status_check" CHECK("postings"."status" IN ('nueva', 'aplicada', 'descartada'))
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `postings_by_status` ON `postings` (`status`,`published_at`);--> statement-breakpoint
CREATE INDEX IF NOT EXISTS `postings_by_company` ON `postings` (`company_id`,`normalized_title`);--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS `postings_platform_external_id_unique` ON `postings` (`platform`,`external_id`);--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `publications` (
	`posting_id` integer NOT NULL,
	`published_at` text NOT NULL,
	PRIMARY KEY(`posting_id`, `published_at`),
	FOREIGN KEY (`posting_id`) REFERENCES `postings`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS `runs` (
	`id` integer PRIMARY KEY NOT NULL,
	`platform` text NOT NULL,
	`started_at` text NOT NULL,
	`finished_at` text,
	`found` integer DEFAULT 0 NOT NULL,
	`new` integer DEFAULT 0 NOT NULL,
	`error` text
);
