#!/usr/bin/env python3
"""
diff_runs.py
-------------
Compares two output files from this project (JSON, as written by
output_writer.save) and reports what changed between them, keyed on `sku` —
Flippa's own listing id.

    python3 diff_runs.py --old saas.2026-09-01.json \\
                          --new saas.2026-09-19.json

Typical use is a scheduled re-run of one of the engines, kept under a dated
filename, diffed against the previous one:

    python3 playwright_scraper.py --url "$URL" --out "saas_$(date +%F)"
    python3 diff_runs.py --old "saas_$(ls -t saas_*.json | sed -n 2p)" \\
                          --new "saas_$(date +%F).json" --out diff.json

Four buckets, each keyed on sku:

  added          — sku present in --new, absent from --old
  removed        — sku present in --old, absent from --new (sold, delisted,
                   or simply off this particular page of this run)
  changed        — sku present in both, with a different price,
                   original_price, discount_pct, currency, status, sale
                   method or monthly profit
  source_changed — sku present in both with a different price, but also a
                   different price_source: one run read Flippa's embedded
                   listing JSON and the other fell back to the rendered card,
                   so the two are not comparable on price. Reported on its own
                   because it says something about our two snapshots, not
                   about the site — and --fail-on-change ignores it.

A row this project's parser could not recover a sku for (None) cannot be
matched across runs at all, so it is counted and reported separately rather
than silently folded into "added"/"removed", which would be wrong on its face.
"""

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

TRACKED_FIELDS = ("price", "original_price", "discount_pct", "currency",
                  "status", "sale_method", "monthly_profit")

# The subset of TRACKED_FIELDS whose comparability depends on price_source
# matching between the two runs — see diff_products.
PRICE_FIELDS = ("price", "original_price", "discount_pct")


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

        # A row whose price_source differs between runs is not comparable on
        # price: one run read the figures out of Flippa's own embedded listing
        # JSON, the other had to read them off the rendered card. Reporting
        # that as a price change would be a false alarm about the SITE when
        # the difference is in our own two snapshots. Non-price fields still
        # compare fine.
        sources = (before.get("price_source"), after.get("price_source"))
        if sources[0] != sources[1] and any(f in field_changes for f in PRICE_FIELDS):
            price_part = {f: v for f, v in field_changes.items() if f in PRICE_FIELDS}
            other_part = {f: v for f, v in field_changes.items() if f not in PRICE_FIELDS}
            source_changed.append({
                "sku": sku, "title": after.get("title"),
                "price_source": {"old": sources[0], "new": sources[1]},
                "changes": price_part,
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
    print(f"[+] {len(result['added'])} added, {len(result['removed'])} removed, "
          f"{len(result['changed'])} changed, "
          f"{len(result['source_changed'])} not comparable on price.")
    for p in result["added"]:
        print(f"  + {p.get('sku')}  {p.get('title')}  {p.get('price')} {p.get('currency')}")
    for p in result["removed"]:
        print(f"  - {p.get('sku')}  {p.get('title')}  {p.get('price')} {p.get('currency')}")
    for c in result["changed"]:
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}" for f, v in c["changes"].items())
        print(f"  ~ {c['sku']}  {c['title']}  {deltas}")
    for c in result["source_changed"]:
        src = c["price_source"]
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}" for f, v in c["changes"].items())
        print(f"  ? {c['sku']}  {c['title']}  {deltas}  "
              f"[price_source {src['old']!r} -> {src['new']!r}: the two runs "
              f"rendered differently, so this is not a site-side price change]")
    unmatchable = result["unmatchable_old"] + result["unmatchable_new"]
    if unmatchable:
        print(f"[!] {unmatchable} row(s) across both files had no sku or a "
              f"duplicate sku, and could not be matched across runs.")


def _run_status(path: str) -> Tuple[Optional[str], Optional[dict]]:
    """Read the `<out>.meta.json` sidecar beside a run's JSON output.

    Returns (status, meta), or (None, None) when there is no sidecar. Every
    engine here writes one whenever it writes output, so a missing sidecar
    means either output from an older version, or a run that wrote nothing —
    in which case there is no file to diff either.
    """
    meta_path = re.sub(r"\.json$", "", path) + ".meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    return meta.get("status"), meta


def _check_comparable(args) -> bool:
    """Refuse an assortment diff between runs that are not both complete.

    This is the failure mode the sidecar exists for: a run cut short on page
    3 of 10 is missing every listing on pages 4-10, and diffing it against
    yesterday's full run reports all of them as `removed` — reading as "these
    businesses were sold" when in fact they were simply never fetched.
    Prices of the SKUs both runs DID see are still comparable, which is why
    this is a refusal with a --force escape hatch rather than a hard error.
    """
    problems = []
    for label, path in (("--old", args.old), ("--new", args.new)):
        status, meta = _run_status(path)
        if status is None:
            continue  # no sidecar: nothing to check, see _run_status
        if status != "complete":
            problems.append(
                f"{label} ({path}) was a {status!r} run — stopped after "
                f"{meta.get('pages_completed')} of {meta.get('pages_requested')} "
                f"page(s), reason {meta.get('stop_reason')!r}")
    if not problems:
        return True

    print("[!] Refusing to diff: at least one run is not a complete view of "
          "the listing, so listings that were never fetched cannot be told "
          "apart from ones that were sold or delisted.")
    for line in problems:
        print(f"      {line}")
    print("    Re-run the incomplete side, or pass --force to compare anyway "
          "(added/removed will include listings that were simply never "
          "fetched).")
    return False


def _assortment_caveats(args) -> List[str]:
    """Reasons the added/removed halves of this diff cannot be trusted.

    A `complete` run is not the same thing as a complete VIEW of the listing.
    `status` answers "did the run get the pages it went for"; `coverage`
    answers "were those pages the whole listing". Two three-page runs of a
    27-page listing are both complete and both windows, and a listing that
    merely moved from page 3 to page 4 between them is absent from the second
    file for a reason that has nothing to do with being sold.

    Price comparison on the SKUs both files hold stays valid either way, which
    is why this annotates the diff instead of refusing it.
    """
    caveats = []
    for label, path in (("--old", args.old), ("--new", args.new)):
        _status, meta = _run_status(path)
        if meta is None:
            continue
        coverage = meta.get("coverage")
        if coverage == "window":
            caveats.append(
                f"{label} ({path}) covered a WINDOW, not the whole listing: "
                f"{meta.get('pages_completed')} page(s) requested out of "
                f"{meta.get('total_results')} result(s). Listings past that "
                f"window were never fetched.")
        elif coverage is None:
            caveats.append(
                f"{label} ({path}) was written before runs recorded their "
                f"coverage, so whether it holds the whole listing is unknown.")
        if meta.get("catalog_mutated"):
            caveats.append(
                f"{label} ({path}) ran while the catalogue was being edited "
                f"(total_results moved from {meta.get('total_results_first')} "
                f"to {meta.get('total_results_last')}), so a listing may have "
                f"been stepped over between two pages.")
    return caveats


def parse_args():
    p = argparse.ArgumentParser(
        description="Diff two flippa-scraper JSON outputs by sku (the listing id).")
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
    caveats = _assortment_caveats(args)
    result["assortment_comparable"] = not caveats
    result["assortment_caveats"] = caveats
    _print_summary(result)
    if caveats:
        print("[!] added/removed above are NOT sold-or-listed conclusions — "
              "read them as entered-window / left-window:")
        for line in caveats:
            print(f"      {line}")
        print("    Price and status changes on the SKUs both files hold are "
              "unaffected. For a real assortment diff, run both sides to the "
              "end of the listing.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[+] Full diff written to {args.out}")

    # `source_changed` is deliberately NOT a reason to fail: it means our own
    # two snapshots rendered differently, not that the site changed anything.
    # Alerting on it would train whoever reads the alert to ignore it.
    # added/removed only count as a change when both files are known to hold
    # the whole listing. Alerting on a listing that simply moved to the next
    # page is the false alarm this whole sidecar exists to prevent.
    changes = [result["changed"]]
    if result["assortment_comparable"]:
        changes += [result["added"], result["removed"]]
    if args.fail_on_change and any(changes):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
