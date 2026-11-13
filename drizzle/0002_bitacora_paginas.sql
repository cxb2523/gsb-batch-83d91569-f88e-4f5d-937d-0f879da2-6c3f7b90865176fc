CREATE TABLE `search_page_logs` (
	`id` integer PRIMARY KEY NOT NULL,
	`platform` text NOT NULL,
	`term` text NOT NULL,
	`place` text NOT NULL,
	`place_label` text NOT NULL,
	`page` integer NOT NULL,
	`outcome` text NOT NULL,
	`parsed` integer DEFAULT 0 NOT NULL,
	`error` text,
	`attempted_at` text NOT NULL,
	CONSTRAINT "search_page_logs_outcome_check" CHECK("search_page_logs"."outcome" IN ('ok', 'sin-novedades', 'sin-paginas', 'bloqueado', 'error'))
);
--> statement-breakpoint
CREATE INDEX `search_page_logs_lookup` ON `search_page_logs` (`platform`,`term`,`place`,`attempted_at`);