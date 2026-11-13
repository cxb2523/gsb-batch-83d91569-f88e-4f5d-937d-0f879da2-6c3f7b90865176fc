# Troubleshooting

Until the catalog arrives, both scripts exit 0 even when nothing was downloaded: a missing `unit.db` and every failed item end in exit code 0. A scheduler or `docker compose ps` will not tell you a run failed. Read the log.

The one exception is the `media-vtt.py` catalog stage: when `<LANG>.json.gz` cannot be downloaded or unpacked, the run exits `1` and logs `Catalog stage failed ...`. That says the catalog never arrived, as opposed to a catalog that arrived and matched no `media-item` entries (which exits `0`).

## `Error in downloading or extracting JSON` with `place.holder` in it

The endpoints are still the placeholders. The error names `NameResolutionError` because `place.holder` does not exist. Set them as [Getting started](getting-started.md#set-the-endpoints) describes. The log then says `Finished processing all media items.` anyway; nothing was downloaded.

## The catalog URL has `en_US.UTF-8` (or another locale) in it

You ran the script outside Docker without setting `LANG`, so it took your shell's locale as the catalog language. Set it on the command line: `LANG=S python src/media-vtt.py`. See [Configuration](configuration.md#environment-variables).

## `PermissionError` or `Read-only file system` on `/vtts` or `/epubs`

Outside Docker the defaults point at `/vtts/` and `/epubs/`. Set `OUTPUT_PATH` and `DB_PATH` to folders you can write to.

## `Error accessing unit.db: unable to open database file`

`publications-epub.py` cannot find `unit.db`. With Compose, put it at `./db/unit.db` next to `docker-compose.yml`; outside Docker, set `UNIT_DB_PATH`. The run stops with `Failed to retrieve LanguageId. Exiting.`

## `No LanguageId found for language 'S' in unit.db`

`unit.db` has no `Language` row whose `Symbol` is your `LANG`. Check the symbol, and that the file is the catalog's `unit.db`.

## The catalog stage failed

`media-vtt.py` logs `Catalog stage failed ...` and exits `1` when the catalog index could not be fetched or unpacked. Nothing else ran, and no per-item status changed. The message names which step failed: `while downloading` (address unreachable, HTTP error) or `while extracting` (`BadGzipFile`, truncated download). Fix the endpoint or the network and run again; the next run retries from scratch.

A catalog that downloads and unpacks but holds no `media-item` entries is a different case: the run logs `Catalog stage succeeded ... but it contained no usable media-item entries`, still prints its summary, and exits `0`. Check `LANG` and that the URL is the catalog, not a single item.

## An item is `exhausted`

`media-vtt.py` retries `failed` items on every run. After `MAX_ATTEMPTS` consecutive failures (default 3) the row becomes `exhausted`, and later runs skip it so a permanently broken item does not cost a request each time. To give it another chance, delete its row:

```bash
sqlite3 vtts/media.db "delete from downloaded_vtts where status = 'exhausted'"
```

The next run starts that item from zero. To keep retrying for longer, raise `MAX_ATTEMPTS`; the column `consecutive_failures` in `media.db` shows how close an item is to the limit, and `attempts` is the lifetime request count kept for auditing.

`publications-epub.py` retries its `failed` and `no_epub` items on every run by itself.

## Reporting a bug

Open an [issue](https://github.com/GeiserX/media-download/issues) with:

- which script, and whether you ran it with Compose or plain Python (with the Python version);
- the log from the start of the run to the first `ERROR` line, with your catalog's address replaced by `place.holder`;
- what the SQLite file holds for the item: the `sqlite3` line from [Usage](usage.md#what-the-output-folder-holds).

Security problems go to the [security policy](https://github.com/GeiserX/media-download/blob/main/SECURITY.md), never a public issue.
