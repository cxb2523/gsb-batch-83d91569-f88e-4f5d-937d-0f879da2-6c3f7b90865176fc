"""Capability routing: turn one capability input into each route's calls, price them, pick the cheapest.

Pricing reads local caches and published tables; it never spends. The chosen route is re-priced on fresh
prices by the provider right before any paid call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from getcheapapi.core import Refused, Stop
from getcheapapi.providers import PROVIDERS, Provider

CATALOG = Path(__file__).resolve().parent / "data" / "catalog.json"


class NotApplicable(Exception):
    """The input lacks a field this route needs."""


def load_catalog() -> dict:
    return {k: v for k, v in json.loads(CATALOG.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def capability(name: str) -> dict:
    catalog = load_catalog()
    if name not in catalog:
        raise Stop(f"unknown capability {name}; known: {', '.join(sorted(catalog))}")
    return catalog[name]


_MISSING = object()


def _value(spec, inp: dict, item=None):
    if not (isinstance(spec, str) and spec.startswith("$")):
        return spec
    expr = spec[1:]
    if expr == "item":
        return item
    joined = expr.endswith("|join")
    expr = expr.removesuffix("|join")
    optional = expr.endswith("?")
    expr = expr.removesuffix("?")
    name, _, default = expr.partition("=")
    value = inp.get(name, _MISSING)
    if value is _MISSING or value is None or value == "":
        if default:
            return int(default) if default.isdigit() else default
        if optional:
            return _MISSING
        raise NotApplicable(f"needs input field {name}")
    return ",".join(map(str, value)) if joined and isinstance(value, list) else value


def render(template: dict, inp: dict, item=None) -> dict:
    out = {}
    for key, spec in template.items():
        value = _value(spec, inp, item)
        if value is not _MISSING:
            out[key] = value
    return out


def _unique_items(inp: dict, field: str) -> list:
    items = inp.get(field)
    if not isinstance(items, list) or not items:
        raise NotApplicable(f"needs a non-empty list in {field}")
    try:
        return list(dict.fromkeys(items))  # dedupe, keep order
    except TypeError:
        raise NotApplicable(f"{field} must be a flat list") from None


def bodies(route: dict, inp: dict) -> list[dict]:
    """The request bodies one route sends for this input."""
    if route.get("each"):
        return [render(route["body"], inp, item) for item in _unique_items(inp, route["each"])]
    chunk = route.get("chunk")
    if chunk:
        items = _unique_items(inp, chunk["field"])
        size = int(chunk["size"])
        return [render(route["body"], {**inp, chunk["field"]: items[i:i + size]}) for i in range(0, len(items), size)]
    return [render(route["body"], inp)]


@dataclass
class Option:
    provider: str
    endpoint: str
    route: dict
    bodies: list = field(default_factory=list)
    usd: float | None = None
    status: str = "ok"  # ok | no key | n/a: ... | error: ...
    official: float | None = None

    @property
    def label(self) -> str:
        model = self.route.get("model")
        return f"{self.provider} {self.endpoint}" + (f" {model}" if model else "")


def expand(cap: dict, inp: dict) -> list[dict]:
    """Media routes list candidate models: one option per model, or just the model asked for."""
    routes = []
    for r in cap["routes"]:
        if "models" in r:
            models = [inp["model"]] if inp.get("model") else r["models"]
            routes += [{**r, "model": m} for m in models]
        else:
            routes.append(r)
    return routes


def plan(cap: dict, inputs: list[dict], clients: dict[str, Provider], only: str | None = None) -> list[Option]:
    """Price every route for these inputs, cheapest first. Routes the user has no key for are priced too
    (from published tables or the bundled snapshot) so the table shows what another provider would save."""
    if cap.get("media") and len(inputs) != 1:
        raise Stop("media capabilities take one input per run; use the yir CLI for batches")
    options = []
    for route in expand(cap, inputs[0]):
        if only and route["provider"] != only:
            continue
        if not only and route.get("explicit_only"):
            continue
        opt = Option(route["provider"], route["endpoint"], route)
        cls = PROVIDERS[route["provider"]]
        client = clients.setdefault(route["provider"], cls())
        try:
            usd = 0.0
            for inp in inputs:
                r_inp = {**inp, "model": route["model"]} if route.get("model") else inp
                calls = bodies(route, r_inp)
                opt.bodies += calls
                if cls.name == "yir" and not cls.configured():
                    continue  # Yir quotes need a key
                mult = len(inp.get(route["price_per"]) or []) if route.get("price_per") else 1
                usd += max(1, mult) * sum(client.estimate(route["endpoint"], b, fresh=False) for b in calls)
            if cls.name == "yir" and cls.configured():
                official = client.official(route["endpoint"], opt.bodies[0])
                opt.official = official if official is not None else None
            if not (cls.name == "yir" and not cls.configured()):
                opt.usd = usd
            if not cls.configured():
                opt.status = "no key"
        except NotApplicable as exc:
            opt.status = f"n/a: {exc}"
        except Stop as exc:
            opt.status = f"error: {str(exc).splitlines()[0][:120]}"
        options.append(opt)
    options.sort(key=lambda o: (o.status not in ("ok", "no key"), o.usd if o.usd is not None else float("inf")))
    return options


def choose(options: list[Option]) -> Option:
    # A route that could not be priced may be the cheapest: moving on to the next would spend more unnoticed.
    unpriced = [o for o in options if o.status.startswith("error") and PROVIDERS[o.provider].configured()]
    runnable = [o for o in options if o.status == "ok"]
    if unpriced and runnable:
        reasons = "; ".join(f"{o.label}: {o.status}" for o in unpriced)
        raise Refused(f"could not price every route, so the cheapest is unknown: {reasons}\n"
                      f"Wait and run again, or ask the user before forcing {runnable[0].provider} with --via.")
    if not runnable:
        reasons = "; ".join(f"{o.label}: {o.status}" for o in options) or "no routes"
        keyless = [o for o in options if o.status == "no key"]
        hint = f"\ncheapest route needs a key for {keyless[0].provider}: {PROVIDERS[keyless[0].provider].site}" if keyless else ""
        raise Stop(f"no route can run: {reasons}{hint}")
    return runnable[0]


def summary(options: list[Option], best: Option, media: bool = False) -> dict:
    """The numbers the user is told after a comparison: how many routes were priced, the pick, and what it
    saves against the dearest priced route (media: against the official price, since models differ in quality)."""
    priced = [o for o in options if o.usd is not None and o.status in ("ok", "no key")]
    out = {"routes": len(priced), "pick": best.label, "calls": len(best.bodies), "usd": round(best.usd or 0, 5)}
    if media:
        dear_label, dear_usd = "official", best.official
    else:
        others = [o for o in priced if o is not best]
        dear = max(others, key=lambda o: o.usd) if others else None
        dear_label, dear_usd = (dear.label, dear.usd) if dear else (None, None)
    if dear_usd and dear_usd > (best.usd or 0):
        saved = dear_usd - (best.usd or 0)
        out |= {"vs": dear_label, "vsUsd": round(dear_usd, 5), "savedUsd": round(saved, 5),
                "savedPct": round(100 * saved / dear_usd)}
    return out


def table(options: list[Option]) -> str:
    priced = [o.usd for o in options if o.usd is not None and o.status == "ok"]
    best = min(priced) if priced else None
    rows = []
    for o in options:
        usd = "     -    " if o.usd is None else f"${o.usd:.5f}"
        ratio = f"x{o.usd / best:.1f}" if best and o.usd is not None else ""
        official = f"  official ${o.official:.4f}" if o.official is not None else ""
        calls = f"{len(o.bodies)} call{'s' if len(o.bodies) != 1 else ''}" if o.bodies else ""
        note = f"  ({o.route['note']})" if o.route.get("note") else ""
        rows.append(f"  {o.label:58} {usd:>11} {ratio:>6}  {calls:9} {o.status}{official}{note}")
    return "\n".join(rows)
