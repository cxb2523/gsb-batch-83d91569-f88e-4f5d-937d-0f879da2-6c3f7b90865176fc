# Stage 8 validation — 2026-09-24

## Starting state

- Active branch: `feat/canonical-dedup`, already created before this task.
- HEAD, local `main`, and cached `origin/main`:
  `ade30013237222d83930b6ae21f0b5b0f6300df5`, Stage 7 PR #6 merge.
- Working tree was clean. Recent history contained the normalization commit and Stage 6
  merge. No fetch or external lookup was performed.
- System Python initially ran 592 discovered tests with five import errors, because it
  lacked Playwright and persiantools. The existing project `.venv` passed all **750 baseline
  tests**. All implementation checks below use that environment; no dependency was added.

The legacy Event required a nonempty title, defaulted timezone to Tehran, used integer-only
price typing, and lacked Stage 7 components/precision and canonical field provenance.
Stage 8 deliberately reconciles those differences without changing discovery or normalization.

## Verification

- `.venv/Scripts/python.exe -m unittest discover -s tests`: **832 passed**, **82 new**.
- `python -m compileall src` in the project environment: passed.
- `python -m pip check` in the project environment: no broken requirements.
- `git diff --check`: passed; Git emits LF/CRLF conversion notices only.
- Tests remain offline. CLI tests block socket connections, browser/subprocess startup,
  collection, and data write methods, and compare complete temporary runtime trees.
- Legacy extraction/normalization tests pass unchanged.

New coverage includes Persian/Arabic/English comparison copies, digit/letter/punctuation
variants, generic words, numeric editions, approximate distinctive overlap, strong and
insufficient pairs, same/cross-publisher matches, conflicting dates/times/locations,
missing-value neutrality, inferred/relative/range/session caution, registration URLs,
all-member bridge prevention, permutation determinism, singleton and Place behavior,
canonical conflicts/provenance, Decimal/TOMAN/IRR, unchanged original wording, incomplete
titles, coherent temporal selection, failures and malformed context isolation, edited
raw history, later-source support, anchor ties, separate carousel/frame slots and CLI selection.

The versioned synthetic `tests/fixtures/canonicalization/cross_source_occurrences.json`
runs website and Instagram discovery through normalization and canonicalization. One
occurrence reported by three sources/two publishers becomes one automatic group; the same
title at the same location on the next date stays separate. Synthetic data establishes
positive matching behavior without presenting invented examples as live-source evidence.

## Local stored-data method

No recollection, external search, browser or OCR was used. Two bounds were inspected:

```bash
python -m gatherradar canonicalize --all-enabled --instagram-evidence --limit 5
python -m gatherradar canonicalize --all-enabled --instagram-evidence --limit 30
```

The second bound covers all available current local raw items, still at most 30 per source.
Website selection is first-seen storage order; Instagram selection is publication recency.
Davvvat/Vadoostan Instagram used stored evidence; Jabama/Emrooz used the reported caption
fallback because no local media evidence was available. Tehran by Tehran had no raw store.

Programmatic runs blocked socket connections, subprocess/browser creation, raw/evidence
append methods and file write helpers. Each bound ran twice with exact `CanonicalReview`
equality and identical rendered output. This compares all pair decisions, groups, canonical
fields, IDs, suggestions, diagnostics and ordering, including retained contexts. A field
audit checked that every selected canonical value and source URL had a supporting member.
SHA-256 hashes of all **nine** existing raw/evidence JSONL files were identical before/after.
No canonical output was written to disk.

## Results

| Source | Raw items, bound 5 / 30 | Event candidates, bound 5 / 30 |
| --- | --- | --- |
| Davvvat Website | 5 / 10 | 5 / 10 |
| Davvvat Instagram | 5 / 5 | 3 / 3 |
| Jabama Events Website | 5 / 5 | 5 / 5 |
| Jabama Events Instagram | 5 / 5 | 4 / 4 |
| Vadoostan Website | 5 / 5 | 4 / 4 |
| Vadoostan Instagram | 5 / 5 | 0 / 0 |
| Emrooz Events Instagram | 5 / 5 | 5 / 5 |
| Tehran by Tehran Instagram | 0 / 0 | 0 / 0 |

| Result | Bound 5 | Bound 30 |
| --- | --- | --- |
| Raw items | 35 | 40 |
| Canonical Events / singletons | 26 | 31 |
| Automatic duplicate groups | 0 | 0 |
| Possible duplicate pairs | 1 | 3 |
| Distinct pairs | 53 | 83 |
| Insufficient pairs | 271 | 379 |
| Rejected contexts / source failures | 0 / 0 | 0 / 0 |
| Place candidates | 0 | 0 |

The larger sample had eight populated titles and **no pair with strong distinctive title
agreement**. Precision was one exact, ten inferred, six ranges and fourteen unknown.
No real pair met the automatic policy. Consequently there were no false automatic merges,
but **real positive duplicate recall is not demonstrated** by this sample. Thresholds were
not reduced to increase group counts. The positive same-publisher/cross-publisher cases
and repeated-title/different-session cases are demonstrated by synthetic tests only.

Review suggestions were structurally:

- Same-publisher website observations sharing an inferred date and city, one missing title,
  with different clocks: separate Events; uncertain clock difference visible.
- Same-publisher range and single-date observations sharing start date/city, one missing
  title: separate Events; neither range nor inferred year establishes a single occurrence.
- Cross-publisher website range/date-only observations sharing start date/city, one missing
  title: separate Events; no automatic cross-publisher identity claim.

These are suggestions for inspection, not confirmed duplicates. The existing same-publisher
website/Instagram observations did not provide sufficient normalized matching evidence.
The one exact Instagram date lacked a title. Recurring and multi-session source observations
remained unresolved/range drafts with upstream diagnostics. No invented canonical title,
timestamp, currency conversion or new source fact was identified in the reviewed outputs.
No real-data false-merge fix or threshold tuning was needed.

## Limitations and repository safety

This is not a recall benchmark or a guarantee of source truth. Different names, multilingual
aliases, generic/truncated titles, location wording, multi-location events, inferred dates,
recurring sessions and source contradictions can leave related observations separate.
Existing discovery omissions are preserved. Place deduplication and live positive-match
validation remain future work; Place passthrough is tested synthetically.

Anchors depend on available local history and stable evidence slots. Earlier imported
history, source/slot removal, evidence regrouping and group splits/merges can change identity.
Stage 9 must persist mappings and review identity evolution. Last-seen metadata reflects
stored captures, not every unchanged collection. Quadratic pair enumeration is bounded by
the offline per-source limit and intended for this small private project.

Only code, tests, synthetic fixtures and documentation are changed. No runtime/private data,
credentials, canonical state files, database, Google integration or new dependency is added.
No commit, push, merge or Stage 9 implementation was performed. The working tree is left
on `feat/canonical-dedup` for owner review.

**STAGE 8 READY FOR OWNER REVIEW**
