# How it works

Two independent scripts, one catalog. Neither talks to the other; they share only the `LANG` setting and the compose file.

## media-vtt.py: subtitles

1. Creates `media.db` with a `downloaded_vtts` table if it does not exist. An existing table gains the `attempts` and `consecutive_failures` counters in place, with `0` for every row already there.
2. Downloads `<base>/<LANG>.json.gz`, unpacks it to `<LANG>.json` in the output folder and deletes the `.gz`. A failure here ends the run with exit code 1 and a `Catalog stage failed ...` log line; nothing after this step runs.
3. Reads the file line by line and keeps each object whose `type` is `media-item` and whose `o.keyParts` has an identifier (`pubS`, or else `docID`), a `track` and a `formatCode`. The log line `Catalog read from ...` separates a read that found nothing from a catalog that never arrived.
4. For each item, looks up `(identifier, track, formatCode)` in `media.db`. `success` and `exhausted` are skipped. `failed` is asked about again. `no_subtitles` is asked about again every run.
5. Otherwise asks `<base>?langwritten=<LANG>&track=<track>&pub=<pubS>` (or `docid=<docID>`) and expects JSON with `files.<LANG>.<format>`: lists of file entries. The first entry, in any format, with a `subtitles.url` wins.
6. Before the request goes out, increments `attempts` (the lifetime count, kept for auditing). Downloads that URL and saves it in the output folder under the last part of the URL's path, decoded. A network error is retried after 2 and 4 seconds within the same run; the third failure counts as one failed attempt for this run.
7. Records `success` (attempt count kept, `consecutive_failures` reset to 0), `no_subtitles` (no entry had subtitles; attempt count kept, `consecutive_failures` reset to 0), or `failed` (no answer, no `files` in it, or the download failed). Each `failed` run adds one to `consecutive_failures`; at `MAX_ATTEMPTS` (default 3, set by environment) the row becomes `exhausted` and is skipped. Deleting the row retries it from zero.
8. Ends with one `Run summary:` line counting the entries processed, and their `success`, `no_subtitles`, `failed`, `skipped` and `exhausted` outcomes.

## publications-epub.py: EPUBs

1. Creates `pubs.db` with a `PublicationState` table if it does not exist.
2. Opens `unit.db` and reads the `LanguageId` whose `Symbol` is `LANG`. No match stops the run.
3. Fetches the manifest JSON, takes its `current` field, downloads that manifest's gzipped catalog and unpacks it to `log` in the output folder: a SQLite database.
4. Lists `TagNumber, Symbol, sym` from its `Publication` table for that language. A `TagNumber` other than 0 is an issue of a periodical, fetched with `pub=<sym>&issue=<TagNumber>`; 0 is a single publication, fetched with `pub=<Symbol>`.
5. Skips each publication `pubs.db` already marks `processed`. For the rest, asks for its files with `fileformat=epub` and expects JSON with `files.<LANG>.EPUB[0].file.url`.
6. Downloads that URL and saves it under the name in the server's `Content-Disposition` header, or `<Symbol>_<TagNumber>.epub` without one. A network error is retried after 2 and 4 seconds.
7. Records `processed`, `no_epub` (no EPUB listed) or `failed`. Only `processed` is skipped next time.

## State

The two SQLite files are the only memory between runs. For `media.db`, the `status` and `consecutive_failures` columns decide what happens next; `attempts` is a lifetime request counter that is kept on `success` and `no_subtitles` so a run can be audited.

| Status | Next run |
|---|---|
| `success` | skipped |
| `no_subtitles` | asked again |
| `failed` | asked again, up to `MAX_ATTEMPTS` consecutive failures |
| `exhausted` | skipped |

Delete a row and the next run fetches that item again; delete the file and the next run starts from nothing (files already in the folder are overwritten, not duplicated, because the names come from the catalog).

## What talks to what

Each script makes HTTPS requests to the addresses you set in the source, and to the file URLs the catalog returns. Nothing else leaves the machine. Both run as root inside their containers. The containers need no extra privileges, and nothing in them listens on a port (the `EXPOSE 80` in the Dockerfiles is unused, and the compose file publishes nothing).
