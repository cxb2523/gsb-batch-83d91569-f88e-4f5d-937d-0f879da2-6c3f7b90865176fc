#!/usr/bin/env python3
"""
diff_runs.py
-------------
Compares two output files from this project (JSON, as written by
output_writer.save) and reports what changed between them, keyed on `sku`.

    python3 diff_runs.py --old mercor.2026-09-01.json \\
                          --new mercor.2026-09-07.json

Typical use is a scheduled re-run kept under a dated filename, diffed against
the previous one:

    python3 playwright_scraper.py --mode listings --out "mercor_$(date +%F)"
    python3 diff_runs.py --old "$(ls -t mercor_????-??-??.json | sed -n 2p)" \\
                          --new "mercor_$(date +%F).json" --out diff.json

Four buckets, each keyed on sku:

  added          — sku present in --new, absent from --old
  removed        — sku present in --old, absent from --new: the listing was
                   filled or withdrawn, or simply fell outside the pages this
                   run fetched
  changed        — sku present in both, with a different title, rate range,
                   pay period, commitment, work arrangement, location, or
                   slot count. See TRACKED_FIELDS.
  source_changed — sku present in both, but one row came from the INDEX
                   (`explore`) and the other from a DETAIL page (`detail`),
                   and they differ on a column only one of the two fills.
                   Reported separately because this says something about our
                   own two snapshots rather than about the listing — and
                   --fail-on-change deliberately ignores it.

TWO THINGS TO KNOW BEFORE READING A DIFF OF THIS SITE
-----------------------------------------------------
**`removed` does not mean filled.** `/explore` is not the whole site: it
held 390 of the 462 listings the sitemap and the index enumerate between
them on 2026-09-18, and the 72 it omits are live jobs. So a listing can
leave a `--mode listings` file because it left the INDEX, not because
anything happened to the job — and a `--mode job` run bounded by `--pages`
holds a slice of the enumeration for the same reason. Two runs are only
comparable as a census when both covered the same ground; `--mode job
--pages 462` is what "the same ground" means here.

Mercor publishes no catalogue total on any route, so there is no site-stated
figure to drift — what a run records instead is its own coverage
(`records_in_payload`, `jobs_enumerated`, `jobs_fetched`).

**`position` and `page` are deliberately not tracked, and here that is a
choice rather than a necessity.** Unlike a sibling site whose serialisation
order wanders between requests, Mercor's `/explore` order was measured
STABLE on 2026-09-18: three fetches about ten seconds apart returned the
identical 390 ids in the identical order, 0 positions differing.

So a position change on this site would be a real change and not noise —
and it is still not diffed, for a reason worth stating rather than
inheriting. Ten seconds is evidence about ten seconds. It says nothing
about whether the ranking is stable across a night, which is the interval
a nightly diff actually spans, and a column that reports churn on every run
teaches a reader to ignore the diff. If someone measures the overnight case
and finds it stable, tracking `position` becomes a defensible change; until
then this is the conservative default and the measurement above is what a
future decision should be argued from.

A row this project's parser could not recover a sku for (None) cannot be
matched across runs at all, so it is counted and reported separately rather
than silently folded into "added"/"removed", which would be wrong on its face.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple

from output_writer import UNIQUE_BY_SKU_MODES
from product_parser import CAREERS_URL, EXPLORE_URL, canonical_url

# What is worth watching on a Mercor listing, and nothing else.
#
# EVERY NAME HERE MUST EXIST ON THE ROW CLASS, and that is not a style rule.
# This tuple arrived from the repo this one was ported from and named 25
# fields, 21 of which `JobPosting` does not have — so the diff compared
# nothing, and a listing whose rate went from 100 to 999 with its status
# changed to `closed` reported "0 changed" and exit 0. A price monitor that
# cannot see a price change is worse than no price monitor, because it
# reports success. `smoke_test.py` now pins every name against the dataclass.
#
# A shop's fields are absent because a job has no price, stock or discount —
# porting them would be dead code that looks load-bearing.
# What changes on a Mercor listing is its PAY, its TERMS, its ELIGIBILITY
# and the client behind it.
#
# `eligible_locations` and `eligible_residence_locations` are lists and
# compare element-wise, which is what you want: a role opening up to a new
# country is a real change.
#
# DELIBERATELY NOT TRACKED, and this one is a measurement rather than an
# oversight — the live supply counters:
#
#     remaining_slots  supplied_slots  available_spots
#     active_contractors_count  recent_candidates_count
#
# They move on their own. Two `--mode listings` runs a few minutes apart on
# 2026-09-18 already differed on one: `remaining_slots` 30 -> 29 and
# `supplied_slots` 0 -> 1, because a contractor was supplied in between.
# Tracking them would make every nightly diff report hundreds of "changes"
# that are the marketplace working normally, and a diff that is always noisy
# is one nobody reads. They are still COLUMNS — a consumer who wants supply
# telemetry has it — they are simply not what `changed` is for.
#
# Also not tracked: `position`, `page`, `scraped_at`, and `data_source`
# (which drives `source_changed` instead). See the module docstring.
TRACKED_FIELDS = (
    # what the job is
    "title",
    "status",
    "listing_type",
    "domain",
    "department",
    "team",
    # what it pays
    "rate_min",
    "rate_max",
    "rate_currency",
    "rate_period",
    "compensation",
    "offers_equity",
    "referral_amount",
    # on what terms
    "commitment",
    "employment_type",
    "hours_per_week",
    # where
    "location",
    "work_arrangement",
    "eligible_locations",
    "eligible_residence_locations",
    # who for
    "company_name",
    "company_brand_visible",
    "company_website",
)

# The subset that only ONE of the two sources populates.
#
# The split runs both ways on this site, which is why it is worth stating.
# An index row (`explore`) has the site's `domain` category and no currency;
# a detail-page row (`detail`) has the currency, the schema.org employment
# type and the company website, and no `domain`. Read off the same listing
# both ways in sample_output.json. So diffing a listings run against a job
# run would report each of these as a change on every row, and none of it
# would be about the job. When the two rows disagree on `data_source`, they are
# reported as `source_changed` rather than as changes (a difference that
# comes with a provenance difference says something about our own two
# snapshots, not about the site).
DETAIL_ONLY_FIELDS = (
    "domain", "employment_type", "rate_currency", "company_website",
)
# Kept as an alias so a caller written against the family's older name still
# works; the two are the same tuple.
PROFILE_ONLY_FIELDS = DETAIL_ONLY_FIELDS


def _load(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _by_sku(products: List[dict]) -> Tuple[Dict[str, dict], int]:
    indexed = {}
    unmatchable = 0
    for p in products:
        sku = p.get("sku")
        if sku is None:
            unmatchable += 1
            continue
        # A run's own output can already hold a duplicate sku (two rows in the
        # same category, or a rerun of dedupe_by_sku's job on older output
        # written before it existed) — keep the first and count the rest as
        # unmatchable rather than letting one clobber the other silently.
        if sku in indexed:
            unmatchable += 1
            continue
        indexed[sku] = p
    return indexed, unmatchable


def diff_products(old: List[dict], new: List[dict]) -> dict:
    old_by_sku, old_unmatchable = _by_sku(old)
    new_by_sku, new_unmatchable = _by_sku(new)

    added = [new_by_sku[sku] for sku in new_by_sku.keys() - old_by_sku.keys()]
    removed = [old_by_sku[sku] for sku in old_by_sku.keys() - new_by_sku.keys()]

    changed, source_changed = [], []
    for sku in old_by_sku.keys() & new_by_sku.keys():
        before, after = old_by_sku[sku], new_by_sku[sku]
        field_changes = {
            field: {"old": before.get(field), "new": after.get(field)}
            for field in TRACKED_FIELDS
            if before.get(field) != after.get(field)
        }
        if not field_changes:
            continue

        # A row whose `data_source` differs between runs is not comparable on
        # the one-source columns: an index row leaves some of them null and a
        # detail row fills them (and the other way round), so every one of
        # them would read as a change and none of it would be about the job. Reporting it as a
        # change would be a false alarm about the site; the other columns
        # still compare fine.
        sources = (before.get("data_source"), after.get("data_source"))
        if sources[0] != sources[1] and any(f in field_changes
                                            for f in PROFILE_ONLY_FIELDS):
            profile_part = {f: v for f, v in field_changes.items()
                            if f in PROFILE_ONLY_FIELDS}
            other_part = {f: v for f, v in field_changes.items()
                          if f not in PROFILE_ONLY_FIELDS}
            source_changed.append({
                "sku": sku, "title": after.get("title"),
                "data_source": {"old": sources[0], "new": sources[1]},
                "changes": profile_part,
            })
            field_changes = other_part
            if not field_changes:
                continue

        changed.append({"sku": sku, "title": after.get("title"),
                        "changes": field_changes})

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "source_changed": source_changed,
        "unmatchable_old": old_unmatchable,
        "unmatchable_new": new_unmatchable,
    }


def _print_summary(result: dict) -> None:
    bounded = result.get("selection_bounded")
    if bounded:
        # A slice moved; nothing here has been shown to be listed or
        # withdrawn. Said in the headline, because a reader who sees "N
        # removed" stops there.
        print(f"[+] {len(result['added'])} entered the slice, "
              f"{len(result['removed'])} left it, "
              f"{len(result['changed'])} changed, "
              f"{len(result['source_changed'])} not comparable across run "
              f"kinds.  ({' and '.join(bounded)} fetched fewer jobs than it "
              f"enumerated, so entered/left says where the SLICE moved, not "
              f"that a listing was added or withdrawn.)")
    else:
        print(f"[+] {len(result['added'])} added, {len(result['removed'])} "
              f"removed, {len(result['changed'])} changed, "
              f"{len(result['source_changed'])} not comparable across run "
              f"kinds.")
    for p in result["added"]:
        print(f"  + {p.get('sku')}  {p.get('title')}  "
              f"@ {p.get('company_name') or '?'}  "
              f"{p.get('compensation') or 'pay not stated'}")
    for p in result["removed"]:
        print(f"  - {p.get('sku')}  {p.get('title')}  "
              f"@ {p.get('company_name') or '?'}  "
              f"{p.get('compensation') or 'pay not stated'}")
    for c in result["changed"]:
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ~ {c['sku']}  {c['title']}  {deltas}")
    for c in result["source_changed"]:
        src = c["data_source"]
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ? {c['sku']}  {c['title']}  {deltas}  "
              f"[data_source {src['old']!r} -> {src['new']!r}: the index and "
              f"a detail page each fill columns the other leaves null, so "
              f"this is not a change in the job]")
    unmatchable = result["unmatchable_old"] + result["unmatchable_new"]
    if unmatchable:
        print(f"[!] {unmatchable} row(s) across both files had no sku or a "
              f"duplicate sku, and could not be matched across runs.")


def _run_status(path: str) -> Tuple[Optional[str], Optional[dict]]:
    """Read the `<out>.meta.json` sidecar beside a run's JSON output.

    Returns (status, meta), or (None, None) when there is no sidecar — which
    is the normal case for output written before run metadata existed, or by
    `scraper_api_client.py` (single fetch, no pagination to cut short).
    """
    meta_path = re.sub(r"\.json$", "", path) + ".meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    return meta.get("status"), meta


# What a run SELECTED, as its sidecar records it. Two complete runs that
# selected different things are both genuinely complete and still not
# comparable: `--domain Finance` against `--domain Law` is two different
# slices of the index, and every listing in one that is not in the other would
# be reported as added or removed when nothing about the SITE changed. This is
# the audit's P2 — `domain_filter` was written into the sidecar by this very
# repo and never read back.
SELECTION_KEYS = ("mode", "domain_filter", "start_url")


def _normal_start_url(mode, url):
    """The address a run started on, with "no --url" meaning the mode's own.

    A listings run with no `--url` and one given `--url
    https://work.mercor.com/explore` selected exactly the same thing, and
    recording `None` for one and the string for the other must not make them
    look different.
    """
    if url:
        try:
            return canonical_url(url)
        except Exception:  # noqa: BLE001 - an unparseable URL compares as itself
            return url
    return {"listings": EXPLORE_URL, "careers": CAREERS_URL}.get(mode)


def _selection(meta: Optional[dict]) -> dict:
    meta = meta or {}
    return {"mode": meta.get("mode"),
            "domain_filter": ((meta.get("domain_filter") or "").strip().lower()
                              or None),
            "start_url": _normal_start_url(meta.get("mode"),
                                           meta.get("start_url"))}


def _bounded(meta: Optional[dict]) -> bool:
    """Whether a `--mode job` run fetched fewer jobs than it enumerated.

    That run is a SLICE, and what a slice contains is decided by `--pages`
    and the order of the sitemap — so a listing absent from it has not been
    shown to be gone.
    """
    meta = meta or {}
    enumerated, fetched = meta.get("jobs_enumerated"), meta.get("jobs_fetched")
    return bool(enumerated and fetched and fetched < enumerated)


def _bounded_runs(args) -> List[str]:
    out = []
    for label, path in (("--old", args.old), ("--new", args.new)):
        _, meta = _run_status(path)
        if _bounded(meta):
            out.append(label)
    return out


def _check_comparable(args) -> bool:
    """Refuse an assortment diff between runs that are not both complete.

    This is the failure mode the sidecar exists for: a run cut short on page
    3 of 10 is missing every product on pages 4-10, and diffing it against
    yesterday's full run reports all of them as `removed` — reading as "these
    products were delisted" when in fact they were simply never fetched.
    Prices of the SKUs both runs DID see are still comparable, which is why
    this is a refusal with a --force escape hatch rather than a hard error.
    """
    problems = []
    modes = {}
    metas = {}
    for label, path in (("--old", args.old), ("--new", args.new)):
        status, meta = _run_status(path)
        if status is None:
            # NOT "nothing to check". A run with no sidecar cannot be told
            # from a partial one, and the family refuses to diff a partial
            # run because its un-fetched pages read as delisted listings.
            # Letting an unverifiable run through is the
            # same hole by another door.
            #
            # This used to be waved through because the Scraper API client
            # wrote rows and no sidecar. It writes one now, so the refusal
            # is something the user can act on rather than a defect of ours.
            problems.append(
                f"{label} ({path}) has no .meta.json beside it, so whether it "
                f"is a complete run cannot be checked. Output written before "
                f"run metadata existed (or by hand) lands here; re-run it, or "
                f"pass --force if you know it is complete.")
            continue
        metas[label] = meta or {}
        mode = (meta or {}).get("mode")
        if mode:
            modes[label] = mode
        if mode and mode not in UNIQUE_BY_SKU_MODES:
            # This tool's whole premise is one row per `sku`, diffed on
            # price. A mode that produces many rows per sku would give a diff
            # whose every line is an artefact of two rows sharing an id, so
            # it is refused outright rather than answered. Both of this
            # repo's current modes qualify; the check is here so that adding
            # one that does not is caught rather than discovered.
            problems.append(
                f"{label} ({path}) is a {mode!r} run, which is not one row "
                f"per sku. This tool diffs one row per sku on price, so there "
                f"is nothing here it can compare.")
        # "empty" is a finished run whose answer was nothing (written only
        # with --allow-empty): complete, so it compares like one.
        if status not in ("complete", "empty"):
            problems.append(
                f"{label} ({path}) was a {status!r} run — stopped after "
                f"{meta.get('pages_completed')} of {meta.get('pages_requested')} "
                f"page(s), reason {meta.get('stop_reason')!r}")
    if len(set(modes.values())) > 1:
        kinds = set(modes.values())
        # `careers` against either marketplace mode is the severe case and
        # deserves its own sentence: the two share NO ids at all, so every
        # row would be reported as both added and removed. `listings`
        # against `job` is milder — same id space, different columns — but
        # still describes the mode change rather than the catalogue.
        if "careers" in kinds and kinds - {"careers"}:
            problems.append(
                f"the two runs are different POPULATIONS ({modes}). Mercor's "
                f"own openings are Ashby records with UUID ids; marketplace "
                f"listings are `list_…` ids. The two sets have no id in "
                f"common, so every row would be reported as both added and "
                f"removed.")
        else:
            problems.append(
                f"the two runs are different modes ({modes}). An index row "
                f"and a detail row carry different columns — the index has "
                f"`domain` and the slot counters, a detail row has the "
                f"company website and a currency — so `added`/`removed` "
                f"would describe the mode change rather than the catalogue.")

    # The two runs must have selected the same thing. Compared AFTER the mode
    # check so a mode difference is reported once, as the mode difference it is.
    if len(metas) == 2 and len(set(modes.values())) <= 1:
        a, b = _selection(metas["--old"]), _selection(metas["--new"])
        differing = {k: (a[k], b[k]) for k in SELECTION_KEYS if a[k] != b[k]}
        if differing:
            problems.append(
                "the two runs selected different things, so `added` and "
                "`removed` would describe the selection and not the "
                "marketplace: "
                + "; ".join(f"{k}: {x!r} vs {y!r}"
                            for k, (x, y) in differing.items()))

    # NO SORT GUARD, and that absence is a measurement rather than an
    # omission. A sibling repo in this family needs one because its default
    # ordering is a paid placement that changes WHICH rows are in the file.
    # Mercor offers no ordering control at all: `/explore` accepts no query
    # parameter of any kind — `?page`, `?limit`, `?offset` and `?domain`
    # each returned a byte-identical payload on 2026-09-18 — so there is no
    # sort to disagree about and no `sort` column on the row. A guard here
    # would have no input and would pass for the wrong reason.
    #
    # What DOES change which rows are in a file here is the MODE, which is
    # guarded above, and in `--mode job` how many pages were fetched out of
    # the enumeration, which the note below reports.

    # And whether either run was CAPPED, which changes what `removed` means.
    for label, path in (("--old", args.old), ("--new", args.new)):
        _, meta = _run_status(path)
        meta = meta or {}
        enumerated = meta.get("jobs_enumerated")
        fetched = meta.get("jobs_fetched")
        if enumerated and fetched and fetched < enumerated:
            print(f"[i] {label} ({path}) fetched {fetched} of the "
                  f"{enumerated} job(s) it enumerated — a complete run, and "
                  f"a slice. A `removed` line may mean the slice moved "
                  f"rather than that a listing was taken down. Use --pages "
                  f"{enumerated} on both runs to compare a full census.")
        # And the one that applies to every --mode listings run, capped or
        # not: /explore is not the whole site. 72 of the 462 listings
        # enumerated on 2026-09-18 appeared only in the sitemap, so a
        # `removed` line in a listings diff can mean "this listing left the
        # index", which is not the same as "this job is gone". 
        # Complete and exhaustive are different words.
        if meta.get("mode") == "listings" and meta.get("records_in_payload"):
            print(f"[i] {label} ({path}) is a /explore run: it holds every "
                  f"listing the index serves, which is not every listing "
                  f"Mercor publishes. A `removed` line may mean a listing "
                  f"left the index rather than that it was filled. "
                  f"--mode job covers the rest.")

    if not problems:
        return True

    # A generic headline, because the reasons below are no longer only about
    # completeness: a mode mismatch and a reviews run are refused too, and a
    # message naming the wrong reason sends the reader looking in the wrong
    # place.
    print("[!] Refusing to diff these two runs:")
    for line in problems:
        print(f"      {line}")
    print("    Re-run the incomplete side, or pass --force to compare anyway "
          "(added/removed will include jobs that were simply never "
          "fetched).")
    return False


def parse_args():
    p = argparse.ArgumentParser(
        description="Diff two mercor-scraper JSON outputs by sku.")
    p.add_argument("--old", required=True, help="Earlier run's JSON output.")
    p.add_argument("--new", required=True, help="Later run's JSON output.")
    p.add_argument("--out", default=None,
                   help="Write the full diff as JSON to this path too.")
    p.add_argument("--fail-on-change", action="store_true",
                   help="Exit 1 if anything was added, removed or changed — "
                        "for a cron job that should only notify on a real diff.")
    p.add_argument("--force", action="store_true",
                   help="Diff even when a run's .meta.json says it was partial "
                        "or failed. Products never fetched by the short run will "
                        "appear as added/removed.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.force and not _check_comparable(args):
        return 2

    try:
        old = _load(args.old)
        new = _load(args.new)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Could not read one of the input files: {e}")
        return 2

    result = diff_products(old, new)
    bounded = _bounded_runs(args)
    if bounded:
        result["selection_bounded"] = bounded
    _print_summary(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[+] Full diff written to {args.out}")

    # `source_changed` is not a reason to fail: it means one row came from a
    # listings run and the other from a job run, so the columns only one of
    # them fills differ. That says something about our own two snapshots
    # rather than about the job, and alerting on it would train whoever
    # reads the alert to ignore it.
    #
    # Nor is movement of a SLICE: when a run fetched fewer jobs than it
    # enumerated, "entered" and "left" describe where `--pages` and the
    # sitemap order put the cut, and a cron job that pages someone for that
    # is paging them for its own configuration.
    moved = [] if bounded else (result["added"] + result["removed"])
    if args.fail_on_change and (moved or result["changed"]):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
