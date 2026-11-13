import requests
import gzip
import shutil
import json
import logging
import os
import sqlite3
import sys
import traceback
import time
from urllib.parse import urlparse, unquote

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def _read_max_attempts():
    """How many failed attempts an item may accumulate before it is exhausted."""
    raw = os.environ.get('MAX_ATTEMPTS', '3')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logging.warning(f"Invalid MAX_ATTEMPTS value {raw!r}; using the default of 3.")
        return 3
    if value < 1:
        logging.warning(f"MAX_ATTEMPTS must be at least 1 (got {value}); using the default of 3.")
        return 3
    return value


LANG = os.environ.get('LANG', 'S')
OUTPUT_PATH = os.environ.get('OUTPUT_PATH', '/vtts/')  # Set to '/vtts/' as per your requirement
DB_PATH = os.environ.get('DB_PATH', '/vtts/media.db')  # Database in '/vtts/'
MAX_ATTEMPTS = _read_max_attempts()  # Consecutive failed runs before an item is 'exhausted'

# Create output directory if it doesn't exist
if not os.path.exists(OUTPUT_PATH):
    os.makedirs(OUTPUT_PATH)

# Ensure the database and table are created
def setup_database(db_path):
    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    if not os.path.exists(db_path):
        logging.info(f"Database does not exist at {db_path}. Creating new database.")
        open(db_path, 'w').close()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Changed 'pubS' to 'identifier'
        cursor.execute('''CREATE TABLE IF NOT EXISTS downloaded_vtts (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                identifier TEXT NOT NULL,
                                track INTEGER NOT NULL,
                                formatCode TEXT NOT NULL,
                                vtt_url TEXT,
                                status TEXT NOT NULL,
                                attempts INTEGER NOT NULL DEFAULT 0,
                                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                                UNIQUE(identifier, track, formatCode)
                              )''')
        # Older databases predate the counters; add them in place, defaulting
        # existing rows to 0, without touching the rows themselves.
        cursor.execute("PRAGMA table_info(downloaded_vtts)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'attempts' not in columns:
            logging.info(f"Adding the 'attempts' column to the existing {db_path} database.")
            cursor.execute(
                "ALTER TABLE downloaded_vtts ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            )
        if 'consecutive_failures' not in columns:
            logging.info(f"Adding the 'consecutive_failures' column to the existing {db_path} database.")
            cursor.execute(
                "ALTER TABLE downloaded_vtts ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error setting up database: {e}")

def get_vtt_state(db_path, identifier, track, formatCode):
    """Return (status, attempts, consecutive_failures) or (None, 0, 0) if no row."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, attempts, consecutive_failures FROM downloaded_vtts "
            "WHERE identifier = ? AND track = ? AND formatCode = ?",
            (identifier, track, formatCode)
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return (
                result[0],
                result[1] if result[1] is not None else 0,
                result[2] if result[2] is not None else 0,
            )
        return None, 0, 0
    except Exception as e:
        logging.error(f"Error checking database for {identifier}, track {track}, format {formatCode}: {e}")
        return None, 0, 0

def is_vtt_processed(db_path, identifier, track, formatCode):
    """Return the recorded status for an item, or None when it has no row."""
    return get_vtt_state(db_path, identifier, track, formatCode)[0]

# Mark a media item as processed
def mark_vtt_as_downloaded(db_path, identifier, track, formatCode, vtt_url, status,
                           attempts=None, consecutive_failures=None):
    """Record the result for an item, keeping counters that are not passed in."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT attempts, consecutive_failures FROM downloaded_vtts "
            "WHERE identifier = ? AND track = ? AND formatCode = ?",
            (identifier, track, formatCode)
        )
        row = cursor.fetchone()
        if attempts is None:
            attempts = row[0] if row and row[0] is not None else 0
        if consecutive_failures is None:
            consecutive_failures = row[1] if row and row[1] is not None else 0
        cursor.execute(
            '''INSERT INTO downloaded_vtts
                   (identifier, track, formatCode, vtt_url, status, attempts, consecutive_failures)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(identifier, track, formatCode) DO UPDATE SET
                   vtt_url = excluded.vtt_url,
                   status = excluded.status,
                   attempts = excluded.attempts,
                   consecutive_failures = excluded.consecutive_failures''',
            (identifier, track, formatCode, vtt_url, status, attempts, consecutive_failures)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Error inserting into database for {identifier} track {track} format {formatCode}: {e}")

def increment_attempt(db_path, identifier, track, formatCode, vtt_url=None):
    """Increment the lifetime attempt count before a request is actually made.

    Also stamps the row 'failed' so an interrupted run leaves a retryable state.
    Consecutive-failure bookkeeping is left to _record_failure.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO downloaded_vtts
                   (identifier, track, formatCode, vtt_url, status, attempts, consecutive_failures)
               VALUES (?, ?, ?, ?, 'failed', 1, 0)
               ON CONFLICT(identifier, track, formatCode) DO UPDATE SET
                   status = 'failed',
                   attempts = attempts + 1
               RETURNING attempts, consecutive_failures''',
            (identifier, track, formatCode, vtt_url)
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        if row:
            return row[0], row[1] if row[1] is not None else 0
        return 1, 0
    except Exception as e:
        logging.error(f"Error incrementing attempts for {identifier} track {track} format {formatCode}: {e}")
        return None

def download_extract_json(catalog_url, output_path):
    """Fetch and unpack the catalog; return the JSON path, or None on any failure."""
    gz_path = os.path.join(output_path, f"{LANG}.json.gz")
    json_path = os.path.join(output_path, f"{LANG}.json")

    try:
        logging.info(f"Downloading catalog from {catalog_url}.")
        response = requests.get(catalog_url, stream=True)
        response.raise_for_status()
        gz_bytes = response.content
    except Exception as e:
        logging.error(
            f"Catalog stage failed while downloading {catalog_url}: "
            f"{type(e).__name__}: {e}"
        )
        return None

    try:
        with open(gz_path, "wb") as gz_file:
            gz_file.write(gz_bytes)

        logging.info("Extracting the JSON")
        with gzip.open(gz_path, "rb") as f_in:
            with open(json_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    except Exception as e:
        logging.error(
            f"Catalog stage failed while extracting {catalog_url} to {json_path}: "
            f"{type(e).__name__}: {e}"
        )
        # Do not leave a half-written archive or index behind for the next run.
        for partial in (gz_path, json_path):
            try:
                os.remove(partial)
            except OSError:
                pass
        return None

    # Delete the .gz file after extraction
    logging.info(f"Deleting {gz_path} after extraction.")
    try:
        os.remove(gz_path)
    except OSError as e:
        logging.warning(f"Could not delete {gz_path} after extraction: {e}")

    return json_path

def extract_media_info(json_path):
    media_info = []
    lines_read = 0
    parse_errors = 0
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                lines_read += 1
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, TypeError) as e:
                    parse_errors += 1
                    logging.warning(f"Skipping unparseable catalog line {line_number}: {e}")
                    continue
                if not isinstance(item, dict) or item.get('type') != 'media-item':
                    continue
                o = item.get('o', {})
                key_parts = o.get('keyParts', {})

                # Get 'identifier' as either 'pubS' or 'docID'
                identifier = key_parts.get('pubS') or key_parts.get('docID')
                track = key_parts.get('track')
                formatCode = key_parts.get('formatCode')

                if identifier and track is not None and formatCode:
                    media_info.append((identifier, track, formatCode, key_parts))
    except Exception as e:
        logging.error(f"Error in extracting media info from {json_path}: {e}")
        return media_info

    logging.info(
        f"Catalog read from {json_path}: {lines_read} JSON lines, "
        f"{parse_errors} unparseable, {len(media_info)} media-item entries matched."
    )
    return media_info

def get_pub_media_links(identifier, track, formatCode, key_parts):
    base_url = "https://place.holder/api/v1/get"

    # Determine whether to use 'pub' or 'docid' parameter
    params = {
        'langwritten': LANG,
        'track': track,
        # 'fileformat' parameter is removed as per your instructions
    }

    if 'pubS' in key_parts:
        params['pub'] = key_parts['pubS']
    elif 'docID' in key_parts:
        params['docid'] = key_parts['docID']
    else:
        logging.error(f"No 'pubS' or 'docID' found in key parts: {key_parts}")
        return None

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error for {identifier} track {track} format {formatCode}: {http_err}")
        return None
    except Exception as e:
        logging.error(f"Error in accessing media links API: {e}")
        return None

def _record_failure(ctx, vtt_url):
    """Count one failed attempt and flip the row to 'exhausted' at the limit."""
    identifier, track, formatCode, attempts, consecutive_failures = ctx
    failures = consecutive_failures + 1
    if failures >= MAX_ATTEMPTS:
        logging.error(
            f"{identifier} track {track} format {formatCode} failed {failures} consecutive "
            f"attempts (limit {MAX_ATTEMPTS}); marking it exhausted and skipping it from now on. "
            f"Delete its row from downloaded_vtts to retry it."
        )
        status = 'exhausted'
    else:
        logging.warning(
            f"{identifier} track {track} format {formatCode} failed attempt {failures} of "
            f"{MAX_ATTEMPTS}; it will be retried on the next run."
        )
        status = 'failed'
    mark_vtt_as_downloaded(
        DB_PATH, identifier, track, formatCode, vtt_url, status,
        attempts=attempts, consecutive_failures=failures,
    )
    return status


def _download_vtt(ctx, vtt_file_url, max_retries):
    """Download one subtitle URL, retrying transient errors; return True on success."""
    identifier, track, formatCode, _attempts, _failures = ctx
    retry_count = 0
    while retry_count < max_retries:
        try:
            vtt_response = requests.get(vtt_file_url, stream=True)
            vtt_response.raise_for_status()

            # Extract the filename from the URL
            parsed_url = urlparse(vtt_file_url)
            filename = os.path.basename(parsed_url.path)
            filename = unquote(filename)  # Decode URL-encoded characters

            # Save VTT file with the original filename
            vtt_filename = os.path.join(OUTPUT_PATH, filename)

            with open(vtt_filename, 'wb') as vtt_output:
                vtt_output.write(vtt_response.content)

            logging.info(f"Downloaded: {vtt_filename}")
            return True

        except requests.exceptions.RequestException as e:
            retry_count += 1
            logging.warning(f"Attempt {retry_count} failed for {identifier} track {track}: {e}")
            logging.debug(f"Exception details: {traceback.format_exc()}")
            if retry_count < max_retries:
                wait_time = 2 ** retry_count
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"All {max_retries} attempts failed for {identifier} track {track}")
        except Exception as e:
            logging.error(f"Unexpected error for {identifier} track {track}: {e}")
            logging.debug(f"Exception details: {traceback.format_exc()}")
            return False
    return False


def download_vtt_files(media_info, max_retries=3):
    """Process catalog entries; return counters for the run summary.

    A failed item is retried on later runs until it accumulates MAX_ATTEMPTS
    consecutive failures, at which point it becomes 'exhausted' and is skipped.
    Deleting its row resets everything and lets it be tried again.
    """
    stats = {
        'processed': 0,
        'success': 0,
        'no_subtitles': 0,
        'failed': 0,
        'skipped': 0,
        'exhausted': 0,
    }
    seen_keys = set()

    def bump(outcome):
        """Tally the record's final state (None means the database write failed)."""
        stats['failed' if outcome in (None, 'failed') else 'exhausted'] += 1

    for identifier, track, formatCode, key_parts in media_info:
        stats['processed'] += 1
        key = (identifier, track, formatCode)
        if key in seen_keys:
            logging.info(f"Duplicate catalog entry {identifier} track {track} format {formatCode}, skipping.")
            stats['skipped'] += 1
            continue
        seen_keys.add(key)

        status, attempts, consecutive_failures = get_vtt_state(DB_PATH, identifier, track, formatCode)

        if status == 'success':
            logging.info(f"Already successfully processed {identifier} track {track} format {formatCode}, skipping.")
            stats['skipped'] += 1
            continue

        if status == 'exhausted' or (
            status == 'failed' and consecutive_failures >= MAX_ATTEMPTS
        ):
            if status != 'exhausted':
                # A database written before the exhausted state existed, already at
                # the limit: record the terminal state now instead of retrying.
                logging.error(
                    f"{identifier} track {track} format {formatCode} already failed "
                    f"{consecutive_failures} consecutive attempts (limit {MAX_ATTEMPTS}); "
                    f"marking it exhausted and skipping it from now on."
                )
                mark_vtt_as_downloaded(
                    DB_PATH, identifier, track, formatCode, None, 'exhausted',
                    attempts=attempts, consecutive_failures=consecutive_failures,
                )
            else:
                logging.info(
                    f"{identifier} track {track} format {formatCode} is exhausted "
                    f"after {consecutive_failures} failed attempts, skipping."
                )
            stats['exhausted'] += 1
            continue

        if not ('pubS' in key_parts or 'docID' in key_parts):
            # No request is possible without an identifier; leave the counter alone.
            logging.error(
                f"No 'pubS' or 'docID' in key parts for {identifier} track {track} "
                f"format {formatCode}, cannot query the media API: {key_parts}"
            )
            bump(_record_failure(
                (identifier, track, formatCode, attempts, consecutive_failures), None
            ))
            continue

        # A real request is about to be made: count it before it goes out.
        counted = increment_attempt(DB_PATH, identifier, track, formatCode)
        if counted is None:
            counted_attempts, counted_failures = attempts + 1, consecutive_failures
        else:
            counted_attempts, counted_failures = counted
        ctx = (identifier, track, formatCode, counted_attempts, counted_failures)

        media_links = get_pub_media_links(identifier, track, formatCode, key_parts)

        if not (media_links and "files" in media_links):
            logging.error(f"No media links available for {identifier} track {track} format {formatCode}")
            logging.debug(f"Response from get_pub_media_links for {identifier} track {track} format {formatCode}: {media_links}")
            bump(_record_failure(ctx, None))
            continue

        vtt_file_url = None

        # We no longer skip items based on title
        formats = media_links["files"].get(LANG, {})

        found_vtt = False
        # Iterate over available formats and files
        for file_format_entries in formats.values():
            for file in file_format_entries:
                # Check if 'subtitles' are available
                subtitles = file.get('subtitles')
                if subtitles and 'url' in subtitles:
                    vtt_file_url = subtitles['url']
                    found_vtt = True
                    break
            if found_vtt:
                break

        if not vtt_file_url:
            logging.warning(f"No subtitles found for {identifier} track {track} format {formatCode}")
            # The item was asked about this run; keep the attempt count for audit.
            mark_vtt_as_downloaded(
                DB_PATH, identifier, track, formatCode, None, 'no_subtitles',
                attempts=ctx[3], consecutive_failures=0,
            )
            stats['no_subtitles'] += 1
            continue

        if _download_vtt(ctx, vtt_file_url, max_retries):
            mark_vtt_as_downloaded(
                DB_PATH, identifier, track, formatCode, vtt_file_url, 'success',
                attempts=ctx[3], consecutive_failures=0,
            )
            stats['success'] += 1
        else:
            bump(_record_failure(ctx, vtt_file_url))

    return stats


def log_run_summary(stats):
    logging.info(
        "Run summary: processed={processed} success={success} "
        "no_subtitles={no_subtitles} failed={failed} skipped={skipped} "
        "exhausted={exhausted}".format(**stats)
    )


def main():
    """Run one collection pass; return the process exit code."""
    setup_database(DB_PATH)
    catalog_url = f"https://place.holder/api/v1/get/{LANG}.json.gz"
    json_path = download_extract_json(catalog_url, OUTPUT_PATH)

    if not json_path:
        logging.error(
            "Catalog stage failed: the catalog archive could not be downloaded or "
            f"extracted from {catalog_url}. No media items were processed; no per-item "
            "status changed. This run did not reach the media-item stage."
        )
        log_run_summary({key: 0 for key in (
            'processed', 'success', 'no_subtitles', 'failed', 'skipped', 'exhausted'
        )})
        return 1

    media_info = extract_media_info(json_path)
    logging.info(f"Total media items to process: {len(media_info)}")

    if not media_info:
        logging.warning(
            f"Catalog stage succeeded ({json_path} was read), but it contained no "
            "usable media-item entries. Check that this is the right language or catalog."
        )

    stats = download_vtt_files(media_info)
    log_run_summary(stats)
    logging.info("Finished processing all media items.")
    return 0


if __name__ == "__main__":
    sys.exit(main())