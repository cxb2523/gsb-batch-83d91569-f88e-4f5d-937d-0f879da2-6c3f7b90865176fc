#!/usr/bin/env python3
"""
diff_runs.py
------------
Compare two andieswim-scraper runs by `sku` and report what moved.

    python3 diff_runs.py --old monday.json --new tuesday.json
    python3 diff_runs.py --old monday.json --new tuesday.json --fail-on-change

    added      a sku in the new run and not the old
    removed    a sku in the old run and not the new — which on this site
               means delisted or unpublished, OR simply outside this run's
               slice if the two runs did not cover the same pages. It does
               NOT mean "outside a site-imposed cap": this store caps
               nothing, so a listing run that reached the end of a
               collection holds all of it
    changed    a tracked field moved: price, currency, stock, or the
               product's own taxonomy
    source_changed
               the two rows were read a different way — a listing row and a
               `--mode product` variant row populate different columns — so
               the difference is about our two snapshots rather than about
               the product, and `--fail-on-change` ignores it

**Three things make two runs incomparable, and all three are refused rather
than diffed.** Each would otherwise produce a diff whose every line is an
artefact:

  * **different `mode`.** A listing run and a product run are different
    grains: a listing names a product once, a product run names each VARIANT.
  * **different `sort`.** On this store that should be impossible: the JSON
    endpoint takes no ordering and every row records `collection-default`.
    The guard is kept as a TRIPWIRE rather than for a live concern — if two
    files ever disagree here, something about how they were produced changed,
    and diffing them would compare two things made differently. (Contrast
    the sibling repo this code came from, where the ordering genuinely
    decides which products are in the file: page 1 of one category under two
    orderings shared 0 of 24 products.)
  * **different `locale`.** This store SETS its prices per market rather than
    converting them — one variant was 112.00 USD, 195.00 CAD, 110.00 GBP,
    175.00 AUD, 130.00 EUR and 21600 JPY on 2026-09-18 — so a cross-market
    diff reports a price change on essentially every row, and none of it is a
    price change. Compare markets deliberately, by joining on `sku` yourself,
    and read the numbers as two prices rather than as a movement. The join is
    exact here: the store is English everywhere, so titles are byte-identical
    across markets and only the money moves.

**`position` and `page` are deliberately not tracked.** They are a property
of the slice a run took, not of the product, and a run that shifts by one
page would otherwise report every row as changed.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Tuple

from output_writer import UNIQUE_BY_SKU_MODES

# What is worth watching on a shop, and nothing else.
#
# This is a price monitor first: `price` and `currency` lead, and `price` is
# compared alongside `price_source` so a number that moved because it was
# read from a different NODE is not reported as a price change (see below).
#
# `in_stock` earns its place because it genuinely varies here — measured over
# 384 tiles, `available` on 377 and `soldout` on 7 — unlike the JSON-LD's own
# availability, which was InStock on 192 of 192 and would have made a
# constant column look like a monitored one.
#
# The taxonomy fields are tracked because a product moving collection, or
# gaining a special-edition flag, is a real editorial change worth seeing.
#
# Deliberately NOT tracked: `position` and `page` (a property of the slice,
# not of the product), `image_url` (the URL carries a content hash that
# changes when the site re-encodes an unchanged photo), and `title`, which is
# printed on every line anyway and whose whitespace the site is inconsistent
# about.
TRACKED_FIELDS = (
    # the point of the exercise
    "price", "original_price", "discount_pct", "currency", "in_stock",
    # how much of it you can actually buy — the column that moves most on a
    # swimwear catalogue, where 116 of 180 products are available in some
    # sizes and not others
    "variants_available", "variants_total",
    # what the product IS
    "category", "product_type", "brand", "color", "size",
    # identity, in case a variant is re-parented between runs
    "base_sku", "product_id",
)

# The subset that ONLY one kind of run populates.
#
# A `--mode product` row is a VARIANT and a listing row is a PRODUCT, so the
# two populate different columns: only a variant row carries `color` and
# `size`, and only a listing row carries the collection it was walked from.
# Diffing one against the other would report every one of these as a change
# and none of it would be about the store. When the two rows disagree on
# `mode`, these are reported as `source_changed` rather than as changes —
# this family's rule (a difference that comes with a provenance
# difference says something about our own two snapshots, not about the site).
#
# Note `sku` itself differs in KIND between the modes (a product id against a
# variant sku), which is why `diff_runs.py` refuses the comparison outright
# rather than relying on this list to clean it up.
PROFILE_ONLY_FIELDS = (
    "collection", "color", "size", "variants_available", "variants_total",
)

# Kept under a second name because that is what this repo's row model calls
# the distinction. `PROFILE_ONLY_FIELDS` is the family's spelling.
PRODUCT_MODE_ONLY_FIELDS = PROFILE_ONLY_FIELDS


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

        # A row whose `mode` differs between runs is not comparable on the
        # mode-specific columns: a listing row carries the collection it was
        # walked from and no size, a `--mode product` variant row the
        # opposite. Every one of them would read as a change and none of
        # it would be about the product. Reporting it as a change would be a
        # false alarm about the site; the other columns still compare fine.
        sources = (before.get("mode"), after.get("mode"))
        if sources[0] != sources[1] and any(f in field_changes
                                            for f in PROFILE_ONLY_FIELDS):
            profile_part = {f: v for f, v in field_changes.items()
                            if f in PROFILE_ONLY_FIELDS}
            other_part = {f: v for f, v in field_changes.items()
                          if f not in PROFILE_ONLY_FIELDS}
            source_changed.append({
                "sku": sku, "title": after.get("title"),
                "mode": {"old": sources[0], "new": sources[1]},
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
    print(f"[+] {len(result['added'])} added, {len(result['removed'])} removed, "
          f"{len(result['changed'])} changed, "
          f"{len(result['source_changed'])} not comparable across run kinds.")
    for p in result["added"]:
        print(f"  + {p.get('sku')}  {p.get('title')}  "
              f"{p.get('price')} {p.get('currency') or ''}")
    for p in result["removed"]:
        print(f"  - {p.get('sku')}  {p.get('title')}  "
              f"{p.get('price')} {p.get('currency') or ''}")
    for c in result["changed"]:
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ~ {c['sku']}  {c['title']}  {deltas}")
    for c in result["source_changed"]:
        src = c["mode"]
        deltas = ", ".join(f"{f}: {v['old']!r} -> {v['new']!r}"
                           for f, v in c["changes"].items())
        print(f"  ? {c['sku']}  {c['title']}  {deltas}  "
              f"[mode {src['old']!r} -> {src['new']!r}: a listing row and a "
              f"variant row fill different columns, so this is not a change "
              f"in the product]")
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
    for label, path in (("--old", args.old), ("--new", args.new)):
        status, meta = _run_status(path)
        if status is None:
            continue  # no sidecar: nothing to check, see _run_status
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
        if status != "complete":
            problems.append(
                f"{label} ({path}) was a {status!r} run — stopped after "
                f"{meta.get('pages_completed')} of {meta.get('pages_requested')} "
                f"page(s), reason {meta.get('stop_reason')!r}")
    if len(set(modes.values())) > 1:
        problems.append(
            f"the two runs are different modes ({modes}). A listing row and a "
            f"detail row carry different fields, so `added`/`removed` would "
            f"describe the mode change rather than the catalogue.")

    # A SORT MISMATCH — a tripwire here rather than a live concern.
    #
    # The sibling repos guard a cross-storefront diff with `source`. This
    # store has ONE host for all 200 of its markets, so `source` is
    # "andieswim.com" on both sides and there is no storefront split for it
    # to catch. What decides which products are in a file here is the LOCALE,
    # guarded after this.
    #
    # The ordering cannot differ between two runs of THIS scraper: the JSON
    # endpoint takes no `sort_by` and every row records `collection-default`.
    # The guard stays because a disagreement would mean the files were
    # produced differently — a code change, or a hand-edited file — and
    # diffing those compares two things made two ways. It is deliberately
    # NOT deleted as dead code: unlike a policy constant nothing reads,
    # this one has a consumer and a condition, it just should never fire.
    sorts = {}
    for label, path in (("--old", args.old), ("--new", args.new)):
        try:
            rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seen = {r.get("sort") for r in rows if r.get("sort")}
        if len(seen) == 1:
            sorts[label] = seen.pop()
        elif len(seen) > 1:
            problems.append(
                f"{label} ({path}) holds more than one sort ({sorted(seen)}) "
                f"— that file merges runs of different orderings, so it is "
                f"not one sample of anything.")
    if len(set(sorts.values())) > 1:
        problems.append(
            f"the two runs used different orderings ({sorts}). The ordering "
            f"should be constant on this store — the JSON endpoint takes no "
            f"ordering — so a disagreement means these two files were "
            f"produced differently, and diffing them compares two things "
            f"made two ways.")

    # A LOCALE MISMATCH, which is this site's most expensive false alarm.
    #
    # This store SETS its prices per market rather than converting them: one
    # variant was 112.00 USD, 195.00 CAD, 110.00 GBP, 175.00 AUD, 130.00 EUR
    # and 21600 JPY on 2026-09-18. 110 GBP is about 148 USD against a 112 USD
    # list, so these are pricing decisions and not conversions. A cross-market
    # diff would report a price change on essentially every row and not one
    # of them would be a price change.
    #
    # `currency` alone cannot stand in for this, because two markets can
    # share one: the euro markets all price in EUR and need not agree.
    locales = {}
    for label, path in (("--old", args.old), ("--new", args.new)):
        try:
            rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seen = {r.get("locale") for r in rows if r.get("locale")}
        if len(seen) == 1:
            locales[label] = seen.pop()
        elif len(seen) > 1:
            problems.append(
                f"{label} ({path}) holds more than one market "
                f"({sorted(seen)}) — this store prices per market, so that "
                f"file is not one price list.")
    if len(set(locales.values())) > 1:
        problems.append(
            f"the two runs read different markets ({locales}). This store "
            f"sets prices per market rather than converting them, so a "
            f"cross-market diff reports a price change on nearly every row "
            f"and none of them is one. Join on `sku` yourself and read the "
            f"two numbers as two prices.")

    # How much of the catalogue each run holds, which changes what `removed`
    # means. Not a refusal — a partial run is a legitimate thing to diff, as
    # long as the reader knows a `removed` line may simply be a product this
    # run never reached.
    for label, path in (("--old", args.old), ("--new", args.new)):
        _, meta = _run_status(path)
        meta = meta or {}
        # This store states no result count, so there is no "x of y pages"
        # line to print. What CAN be said is whether the run reached the end
        # of the listing: `stop_reason` records it, and a run that stopped
        # early holds a slice rather than a collection.
        stop = meta.get("stop_reason")
        done = meta.get("pages_completed")
        if stop and stop not in ("no_new_products", "completed",
                                 "single_page_mode"):
            print(f"[i] {label} ({path}) stopped with stop_reason={stop!r} "
                  f"after {done} page(s), so it may hold only part of the "
                  f"listing. A `removed` line may mean the product fell "
                  f"outside this run's slice rather than that it was "
                  f"delisted.")
        if meta.get("catalog_count") is not None:
            print(f"[i] {label} ({path}) reports catalog_count="
                  f"{meta['catalog_count']}. That is the collection index's "
                  f"`products_count` and is NOT a count of products the "
                  f"storefront serves (measured 472 against 180) — do not "
                  f"read a gap against it as missing rows.")

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
          "(added/removed will include products that were simply never "
          "fetched).")
    return False


def parse_args():
    p = argparse.ArgumentParser(
        description="Diff two andieswim-scraper JSON outputs by sku.")
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
    _print_summary(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[+] Full diff written to {args.out}")

    # `source_changed` is not a reason to fail: it means one row came from a
    # listing run and the other from a profile run, so the columns only a
    # profile fills differ. That says something about our own two snapshots
    # rather than about the product, and alerting on it would train whoever
    # reads the alert to ignore it.
    if args.fail_on_change and (result["added"] or result["removed"] or result["changed"]):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
