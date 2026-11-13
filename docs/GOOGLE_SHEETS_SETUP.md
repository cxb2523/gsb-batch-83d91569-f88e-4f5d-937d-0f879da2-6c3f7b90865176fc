# Optional personal Google Sheets API setup

Default Stage 9 uses local SQLite/XLSX and requires no Google account. This optional
adapter retains its own remote review history; it does not import Google edits into
SQLite. Live OAuth/Sheets validation remains pending and is not a local readiness blocker.

The optional integration uses personal-user OAuth 2.0 Desktop authentication with the official Google
Python libraries. It requests only `https://www.googleapis.com/auth/spreadsheets`.
This scope covers the account's spreadsheets; Google does not offer a Sheets scope
restricted to one workbook. GatherRadar targets only the explicitly configured workbook.
No Drive scope/API, service account, folder management or sharing automation is needed.

## Configure once

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create/select
   your project. Enable **Google Sheets API** for that project.
2. In **Google Auth Platform**, configure the app's branding/contact information.
3. Choose **External** audience for a personal Google account. If the app is in
   **Testing**, add your own Google account under test users.
4. Create an OAuth client ID with application type **Desktop app**.
5. Download the JSON credential to a local private path. For example, use
   `data/auth/google/credentials.json` inside the ignored runtime directory.
   GatherRadar cannot create this credential for you. Never paste its contents
   into chat, logs or Git-managed configuration.
6. Activate the project `.venv`, install with `python -m pip install -e ".[google-sheets]"`, then run:

   ```bash
   python -m gatherradar auth google --credentials "data/auth/google/credentials.json"
   python -m gatherradar sheets status
   python -m gatherradar sheets setup
   python -m gatherradar sheets status
   ```

Authorize in the browser within three minutes. The loopback listener binds a local
port; it does not ask you to paste authorization codes. The credential input is not
copied into configuration. Google token material, including refresh credentials, is
saved atomically in ignored `data/auth/google/token.json`. Do not share this file.
POSIX permissions are limited to the owner where supported; Windows access relies
on the existing private user-directory ACL. Callback and token-library logs are
suppressed during auth. API transport timeout is 30 seconds.

The first status check may report a configured token but no workbook. `setup` creates
one GatherRadar workbook and prints its URL. The returned ID/URL and schema version
live in ignored `data/google/sheets_state.json`. Repeating setup preserves review data.
`setup --new` deliberately creates a separate workbook without deleting the old one.
The owner can move/share the workbook manually in Google Drive.

Google's testing-mode OAuth restrictions can require reauthorization. In particular,
refresh tokens for External apps in Testing normally expire after seven days when
requesting scopes beyond basic profile information. This is a Google app-status
limitation, not a reason to commit or reuse credentials from another application.

## Publish an existing local run

```bash
python -m gatherradar sheets export --run latest
```

This reads SQLite, contacts Google only for publication, and does not collect, analyze
or run OCR. Local human review seeds new remote identities; existing Google review
wins. There is no reverse synchronization. `--db` selects another local database.

## Legacy direct Google workflows

```bash
python -m gatherradar sheets refresh --all-enabled --days 14
python -m gatherradar sheets refresh --all-enabled --days 14 --skip-instagram-evidence
python -m gatherradar sheets sync --all-enabled --days 14 --limit 5
```

`sheets refresh` acquires current public data, with Instagram evidence/OCR by default.
`--skip-instagram-evidence` is caption-only. `sheets sync` uses stored data and
stored evidence; it does not collect or run OCR, but does call Google Sheets.
Both print a run ID before work, support `--source` repeatedly or `--all-enabled`,
and accept `--days 1..90`, `--limit 1..30`, and `--review-timezone`.
The same stable Event may legitimately appear in several historical snapshots.

## Recovery without overwriting history

- **Missing/revoked/expired token:** run `auth google` again using the local Desktop
  credential. Do not paste token or credential contents in a report.
- **Workbook unavailable:** check the signed-in account, workbook permissions and
  whether it was deleted. Configure the existing GatherRadar workbook with
  `--spreadsheet-id` or `GATHERRADAR_SPREADSHEET_ID`; `sheets setup` persists an
  explicitly selected existing workbook after validating its schema. Other commands
  use the override for that invocation only.
- **Unrecognized/newer schema or edited machine headers:** inspect/restore the
  workbook's machine structures. GatherRadar refuses to guess or reset them.
- **Interrupted/quota-limited sync:** retry the exact command/options with
  `--run-id <printed-id>`. The workbook run index is authoritative. Completed IDs
  report `already synced` and do not recollect. Incomplete runs can recreate only
  their own marked temporary tabs, never completed snapshots. Incomplete refresh
  retries may collect again, retaining the original run reference timestamp.
- **Lost create response:** local `creation_pending` prevents a silent second
  workbook. Inspect Google Sheets, find the created GatherRadar workbook and use
  `sheets setup --spreadsheet-id <existing-id>`. If no workbook was created, clear
  the local pending flag deliberately before retrying setup. Do not blindly use `--new`.
- **Local process crash:** if `data/google/sheets_state.lock` remains, first verify
  that no GatherRadar process is running; only then remove that lock file manually.
  The lock is not stolen automatically. Use one writer/runtime directory on one
  computer; distributed concurrency is not supported.

An uncertain publication response is reconciled by re-reading the run index.
Snapshot rename, run append, duplicate queue updates and identity updates share
one atomic Google batch. Temp values/formatting are verified before that batch.
If reconciliation cannot reach Google, the run stays unconfirmed locally; retry
the same run ID later. There is no automatic historical repair or deletion.

Avoid sorting/inserting rows in permanent machine tables during a sync. Human
decisions/notes in the duplicate queue are excluded from update requests. Carry-
forward reads Event IDs, so sorting historical Event rows or renaming snapshot tabs
is supported. Removing identity/review headers or whole historical tabs causes a
safe refusal instead of silently losing personal state.

## Optional adapter live acceptance sequence

After offline tests pass and the owner configures Desktop OAuth:

1. Authenticate, check status, set up the workbook, and check status again.
2. Open the returned workbook; inspect Persian permanent tabs and hidden machine tabs.
3. Run a bounded `sheets sync`; verify rows, direct links, Jalali weekdays/dates,
   RTL, hidden technical columns, filters and dropdowns in the Google-rendered UI.
4. Edit one Event decision/note, create a new snapshot, and verify both carry-forward
   and the unchanged first snapshot. Check run navigation and duplicate review.
5. Only then run a bounded refresh (for example one website with `--limit 2`),
   inspect exact membership, failures, date filtering and immutable history.
6. Verify raw/evidence hashes around sheet-only sync. Only the explicitly requested
   refresh may legitimately append new source observations/evidence.

Do not put private workbook IDs/URLs or credential values in committed documentation.
See [actual Stage 9 validation](STAGE9_VALIDATION.md) for what has been performed.

## Official references

- [Sheets Python quickstart and Desktop OAuth](https://developers.google.com/workspace/sheets/api/quickstart/python)
- [Sheets scope capabilities](https://developers.google.com/workspace/sheets/api/scopes)
- [Atomic batch updates](https://developers.google.com/workspace/sheets/api/guides/batch)
- [OAuth refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
