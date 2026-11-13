# Wappalyzer custom overlay - consolidation (2026-10-22)

Three repos vendored the same enthec/webappanalyzer base dataset (the a-z, `_`,
categories and groups files hash identically: sha256 `064b72fe...a818`) but each
carried its own custom overlay, and the overlays had drifted. This records the
entry-by-entry diff taken before consolidating, the decision on where the single
canonical overlay lives, and every detection change a consumer sees as a result.

## Before: three overlays

| Repo | File | Techs | Meta keys | Engine loader |
|---|---|---:|---|---|
| flarecrawl | `src/flarecrawl/wappalyzer_data/custom_fingerprints.json` | 104 | `_meta`, `_disabled`, `_disabled_meta`, `_added_meta` | list/dict promotion, `_disabled` honoured, implies pruned |
| Fathom | `src/fathom/clients/wappalyzer_data/fathom_custom.json` | 11 | `_meta` | basic merge (no `_disabled`, no promotion) |
| OTDB | `otdb/clients/wappalyzer_data/otdb_custom.json` | 60 | `_meta` | basic merge (identical to Fathom's) |

Fathom and OTDB each carry their own copy of the engine (`clients/wappalyzer.py`,
616 lines, identical apart from the overlay filename); its `analyze()` logic is
the same as flarecrawl's. Only the overlay loader differs. Neither Fathom nor OTDB
shipped `LICENSE.wappalyzer_data` next to the GPL-3.0 data.

## Entry-by-entry diff

**Union: 104 techs, and flarecrawl already has all of them.** Every Fathom and
OTDB tech name exists in flarecrawl's overlay.

- Identical to flarecrawl: Fathom 2 of 11 (Craft CMS, Lightspeed Restaurant), OTDB
  43 of 60.
- Differing only in `_overlay_note` provenance text (no pattern change): OpenTable,
  Square Online, Mr Yum (OTDB), Cobber, Nabooki, NewBook, STAAH, Ventrata,
  Adrenaline, Experience Oz.
- flarecrawl sets `cats` where the others don't: SevenRooms (93), FareHarbor (104),
  Rezdy (104), SiteMinder (32), Bokun (104), ATDW (1). For techs that exist upstream
  the loader never overwrites `cats`, so only ATDW (overlay-only) gains a category.
- flarecrawl has extra patterns (pure additions): ResDiary (`rd-widget-frame`,
  `resdiary\.\w+/widget`), me&u (`meandu.com` scriptSrc + iframe), Quandoo
  (`quandoo-booking-widget`, `booking-widget\.quandoo\.com`, js `qdoo`), Dimmi
  (dimmi/thefork iframes), Bokun (5 widget/CDN patterns), ATDW (4 patterns), Mr Yum
  vs Fathom (`mryum\.com/(?:menu|order)`).

**Real conflicts (a pattern present elsewhere but not in flarecrawl): two.**

| Tech | Fathom / OTDB had | flarecrawl had | Canonical |
|---|---|---|---|
| Bento | dom `a[href*='bfresco.com']` (both) | tightened to `.bfresco.com/menu`, `.bfresco.com/order`, iframe `.bfresco.com/`, html `<sub>.bfresco.com/(menu\|order\|cart\|checkout)` | **flarecrawl's tightened form.** The apex `bfresco.com` is an unrelated decorative-arts site that self-links; the loose selector was a known false positive (flarecrawl 2026-06-02, guarded by `test_bento_pattern_requires_subdomain_not_apex`). This is the one deliberate narrowing. |
| Quandoo | scriptSrc `quandoo\.\w+` (Fathom only) | not present | **Added to canonical.** Specific enough (needs `quandoo.` in a script URL) that it cannot fire on unrelated pages. Broadens Quandoo for flarecrawl and OTDB. |

Text-only differences (Mr Yum / me&u descriptions) take flarecrawl's fuller wording.

**Entries that touch the upstream base.** 54 of the 104 techs exist upstream, so
the overlay extends them rather than adding them (Craft CMS, SevenRooms, OpenTable,
ResDiary, Quandoo, Bento, Square Online, Tailwind CSS, the Node/JS/PHP implies
patches, and others). The loader extends lists and merges dicts; it never replaces
an upstream pattern. Plus `_disabled` removes six upstream techs after the merge:
Element UI, Cart Functionality, Google Sites, C3.js, Contentful, ZURB Foundation
(chronic false positives; corpus precision 0.621 to about 0.9 with no recall loss,
see `_disabled_meta`).

## Decision: flarecrawl owns the file, consumers vendor a stamped copy

Canonical: `flarecrawl/src/flarecrawl/wappalyzer_data/custom_fingerprints.json`.
It is the superset, and the only copy with a validation corpus
(`tests/bench_tech_detect.py`, `tests/validate_custom_overlay.py`).

Consumers get a byte-identical copy plus a provenance stamp from
`scripts/sync_overlay.py`:

```
uv run python scripts/sync_overlay.py <consumer data dir>          # copy + stamp + licence
uv run python scripts/sync_overlay.py <consumer data dir> --check  # exit 1 on drift
```

It writes `custom_fingerprints.json`, `LICENSE.wappalyzer_data`, and
`custom_fingerprints.source.json` (`{canonical, commit, sha256}`). Each consumer's
own test suite asserts the vendored file still hashes to the stamp, so a hand edit
in a consumer turns its gate red. Fixes go to flarecrawl, then get re-synced.

Options considered:

| Option | Coupling | Why not |
|---|---|---|
| Fathom and OTDB import `flarecrawl.wappalyzer` | Heavy: pulls flarecrawl's crawler, CDP and lxml deps into two repos that use none of them; OTDB's `clients` extra exists precisely to drop external CLI deps. Overlay updates would wait on flarecrawl releases. | Most coupling, and a packaging decision |
| Small shared data package (`e7-techprints`) | Light at runtime, but needs a new repo plus publishing or git-URL pins in every consumer | A packaging and publishing call that belongs to Mack. Worth it if a fourth Python consumer appears. |
| **Stamped vendored copy** (chosen) | None at runtime; one-way data flow; works for non-Python consumers (PHPScan is JS) | Copies can go stale (but not silently diverge): `--check` and the stamp test catch that |

## Detection changes per consumer (none silent)

**flarecrawl** (and PHPScan, which vendors flarecrawl's file):
- Craft CMS: meta generator `SEOmatic` and `/cpresources/` asset paths (see below).
- Quandoo: scriptSrc `quandoo\.\w+`.

**Fathom and OTDB** move to the canonical file and to flarecrawl's loader semantics:
- Fathom gains 93 overlay techs, OTDB 44 (frameworks, hosting, tourism booking engines
  and PMS they lacked; 46 and 6 of them respectively are absent from upstream) plus the extra patterns listed above.
- The six `_disabled` upstream techs (including Contentful) no longer appear.
- Bento uses the tightened pattern (the loose apex match is gone).
- List-vs-dict `dom` overlay entries now actually fire, where the old loader
  silently dropped them.
- Craft CMS and Quandoo as for flarecrawl.

Measured 2026-10-22: every pattern in each consumer's old overlay was turned into a
synthetic fixture (flarecrawl's `tests/validate_custom_overlay.py` synthesiser) and
run through the old engine+overlay and the new engine+canonical overlay.

| Consumer | Signals that stopped firing | Signals that newly fire |
|---|---|---|
| Fathom | `Bento dom a[href*='bfresco.com']` (intended) | SevenRooms `iframe[src*='sevenrooms.com']`, ResDiary `a[href*='resdiary']` (list-vs-dict dom promotion) |
| OTDB | same Bento selector (intended) | same two |
| flarecrawl | none | none (against its old overlay's patterns) |

Each repo also carries a customer-embed test table (60 vendors: booking engines, PMS,
payments, Craft); all 60 fire on OTDB's and flarecrawl's old and new setups (Fathom's old setup
fired only its own 11). With the overlay emptied, 59 of flarecrawl's 67 tests go red,
and 61 of 68 in each consumer.

Loader note: flarecrawl's loader treats the `_added_meta` documentation block as a
tech entry (a harmless phantom with no patterns, so its tech count is one higher). The
consumer loaders drop it with the other `_` keys.

## Craft CMS markers added 2026-10-22

Found on evolution7.com.au, a fully CDN-cached Craft site that exposes no Craft
headers or cookies:

- `meta.generator`: `(?:Craft CMS|SEOmatic)`. nystudio107 SEOmatic is a Craft-only
  plugin, and it sets `<meta name="generator" content="SEOmatic">`. Upstream already has
  an `SEOmatic` tech (`^SEOmatic$`) that implies Craft CMS, so these sites were already
  detected through the implies chain. The direct marker makes Craft fire on its own
  evidence, so the detection no longer hangs on an upstream entry staying as it is.
- `scriptSrc` `/cpresources/` and html `(?:src|href)=["'][^"']*/cpresources/`:
  Craft publishes plugin and control-panel assets under `/cpresources/`. The html
  pattern requires an attribute value, so a blog post that mentions the path in
  prose doesn't match.

The bare word "Craft" is never matched: agency sites that sell Craft (Evolution 7
included) name it in titles, keywords and nav copy.
