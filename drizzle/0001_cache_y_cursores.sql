CREATE TABLE `detail_cache` (
	`platform` text NOT NULL,
	`external_id` text NOT NULL,
	`description` text,
	`fetched_at` text NOT NULL,
	PRIMARY KEY(`platform`, `external_id`)
);
--> statement-breakpoint
CREATE TABLE `keyword_cursors` (
	`platform` text NOT NULL,
	`term` text NOT NULL,
	`searched_at` text NOT NULL,
	PRIMARY KEY(`platform`, `term`)
);
