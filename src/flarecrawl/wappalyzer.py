"""Technology detection via Wappalyzer fingerprints.

Pure offline analysis - no network calls. Takes HTML + headers as input,
returns detected technologies with categories and versions.

Fingerprint database vendored from enthec/webappanalyzer (GPL-3.0 data,
~7,500 technologies) plus a custom overlay of ~60 additional fingerprints
(CMS platforms, hospitality/tourism booking engines, accommodation PMS,
channel managers, CSS frameworks, POS systems). See
LICENSE.wappalyzer_data alongside the data dir for the GPL-3.0 notice
covering the upstream fingerprint files.

Usage:
    from flarecrawl.wappalyzer import WappalyzerClient

    client = WappalyzerClient()
    detections = client.analyze(html=page_html, headers=response_headers)
    # [Detection(name="WordPress", version="6.4", categories=["CMS"], ...), ...]

Sections: Detection / WappalyzerClient (load + overlay merge, analyze) /
module singleton / pattern parsing helpers / DOM element matching.
Fathom, OTDB and PHPScan (JS) carry ports of analyze(); behaviour changes
here should be mirrored there.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "wappalyzer_data"


@dataclass
class Detection:
    """A detected technology."""
    name: str
    version: str = ""
    confidence: int = 100
    categories: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    website: str = ""
    description: str = ""
    saas: bool = False
    pricing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "categories": self.categories}
        if self.version:
            d["version"] = self.version
        if self.confidence < 100:
            d["confidence"] = self.confidence
        if self.groups:
            d["groups"] = self.groups
        if self.website:
            d["website"] = self.website
        if self.saas:
            d["saas"] = True
        if self.pricing:
            d["pricing"] = self.pricing
        return d


class WappalyzerClient:
    """Offline technology detector using Wappalyzer fingerprints.

    Loads the fingerprint database once (lazy, thread-safe), then analyzes
    HTML + headers for technology matches. No network calls.
    """

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._techs: dict[str, dict] | None = None
        self._categories: dict[str, dict] | None = None
        self._groups: dict[str, dict] | None = None
        self._load_lock = threading.Lock()

    def _load(self) -> None:
        """Load fingerprint database (lazy, once, thread-safe)."""
        if self._techs is not None:
            return
        with self._load_lock:
            if self._techs is not None:
                return

            techs: dict[str, dict] = {}
            for f in self._data_dir.glob("[a-z_].json"):
                if f.name in ("categories.json", "groups.json"):
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    techs.update(data)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load {f.name}: {e}")

            # Custom fingerprint overlay - merges with the upstream DB.
            # Extends list-valued fields (html, scriptSrc, ...) and dict-
            # valued fields (meta, headers, ...) for techs that already
            # exist upstream; adds wholly-new techs verbatim. A top-level
            # `_disabled` array removes techs from the merged DB - used
            # to suppress upstream fingerprints with chronic false-
            # positive problems (Element UI, Google Sites, etc.).
            custom_file = self._data_dir / "custom_fingerprints.json"
            if custom_file.exists():
                try:
                    custom = json.loads(custom_file.read_text(encoding="utf-8"))
                    custom.pop("_meta", None)
                    custom.pop("_disabled_meta", None)
                    disabled = custom.pop("_disabled", None) or []
                    for tech_name, fingerprint in custom.items():
                        if not isinstance(fingerprint, dict):
                            continue
                        fingerprint.pop("_overlay", None)
                        if tech_name in techs:
                            existing = techs[tech_name]
                            for key, value in fingerprint.items():
                                existing_val = existing.get(key)
                                if isinstance(value, list) and isinstance(existing_val, list):
                                    for item in value:
                                        if item not in existing_val:
                                            existing_val.append(item)
                                elif isinstance(value, dict) and isinstance(existing_val, dict):
                                    existing_val.update(value)
                                elif isinstance(value, list) and isinstance(existing_val, dict):
                                    # Overlay declared a list (e.g. `dom`:
                                    # ["a[href*=...]"]) but upstream stores
                                    # this field as a dict (e.g. `dom`:
                                    # {selector: {attributes: ...}}). Without
                                    # this branch the overlay value falls
                                    # through to "key not in existing" and is
                                    # silently dropped. Promote bare selector
                                    # strings to {selector: {}} so the overlay
                                    # signals actually fire.
                                    logger.debug(
                                        "overlay merge: promoting list -> dict "
                                        "for %s.%s", tech_name, key
                                    )
                                    for sel in value:
                                        if isinstance(sel, str) and sel not in existing_val:
                                            existing_val[sel] = {}
                                elif isinstance(value, dict) and isinstance(existing_val, list):
                                    logger.debug(
                                        "overlay merge: promoting upstream list -> dict "
                                        "for %s.%s", tech_name, key
                                    )
                                    promoted: dict = {
                                        sel: {} for sel in existing_val
                                        if isinstance(sel, str)
                                    }
                                    promoted.update(value)
                                    existing[key] = promoted
                                elif key not in existing:
                                    existing[key] = value
                        else:
                            techs[tech_name] = fingerprint
                    # Strip disabled techs AFTER overlay merge so the merge
                    # logic is unaffected. Also drop them from all `implies`
                    # chains so a high-confidence tech doesn't drag a
                    # disabled tech back in via the implies resolver.
                    if disabled:
                        disabled_set = set(disabled)
                        for name in list(techs.keys()):
                            if name in disabled_set:
                                del techs[name]
                                continue
                            implies = techs[name].get("implies")
                            if implies:
                                if isinstance(implies, list):
                                    techs[name]["implies"] = [
                                        impl for impl in implies
                                        if _implied_name(impl) not in disabled_set
                                    ]
                                elif isinstance(implies, str):
                                    if _implied_name(implies) in disabled_set:
                                        techs[name].pop("implies", None)
                    logger.debug(
                        f"Loaded {len(custom)} custom fingerprints; "
                        f"disabled {len(disabled)} upstream"
                    )
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load custom_fingerprints.json: {e}")

            cat_file = self._data_dir / "categories.json"
            categories = json.loads(cat_file.read_text(encoding="utf-8")) if cat_file.exists() else {}
            self._categories = categories

            grp_file = self._data_dir / "groups.json"
            self._groups = json.loads(grp_file.read_text(encoding="utf-8")) if grp_file.exists() else {}

            # Assign last so the unguarded fast-path check above is sound:
            # a partially-populated _techs would leak to concurrent readers.
            self._techs = techs

            logger.debug(f"Loaded {len(techs)} technologies, {len(categories)} categories")

    def _cat_name(self, cat_id: int) -> str:
        assert self._categories is not None
        return self._categories.get(str(cat_id), {}).get("name", str(cat_id))

    def _cat_groups(self, cat_id: int) -> list[str]:
        assert self._categories is not None and self._groups is not None
        group_ids = self._categories.get(str(cat_id), {}).get("groups", [])
        return [self._groups.get(str(g), {}).get("name", str(g)) for g in group_ids]

    def analyze(
        self,
        html: str = "",
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        script_src: list[str] | None = None,
        meta: dict[str, str] | None = None,
        js_globals: dict[str, str | None] | None = None,
        url: str = "",
    ) -> list[Detection]:
        """Analyze page content for technology fingerprints.

        Args:
            html: Full HTML source of the page.
            headers: HTTP response headers (case-insensitive matching).
            cookies: Cookie name->value mapping.
            script_src: List of <script src="..."> URLs found on page.
            meta: <meta name="..." content="..."> mapping.
            js_globals: Dict of JS global paths -> values from browser probe.
            url: Page URL (for URL-pattern matching).

        Returns:
            List of Detection objects, sorted by confidence (highest first).
        """
        self._load()
        assert self._techs is not None

        # Pre-extract script srcs and meta tags from HTML if not provided
        if script_src is None and html:
            script_src = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if meta is None and html:
            meta = {}
            for m in re.finditer(r'<meta\s+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE):
                meta[m.group(1).lower()] = m.group(2)
            # Also match reversed order (content before name)
            for m in re.finditer(r'<meta\s+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']([^"\']+)["\']', html, re.IGNORECASE):
                meta[m.group(2).lower()] = m.group(1)

        headers = {k.lower(): v for k, v in (headers or {}).items()}
        cookies = cookies or {}
        script_src = script_src or []
        meta = {k.lower(): v for k, v in (meta or {}).items()}

        detections: dict[str, Detection] = {}
        # Views of `html` shared by every fingerprint, each built at most
        # once per call. Building them per tech cost ~12 s on a 1.4 MB page.
        page = _Page(html)

        for tech_name, tech in self._techs.items():
            confidence = 0
            version = ""

            # --- scriptSrc: regex match on <script src> URLs ---
            for pattern in _as_list(tech.get("scriptSrc", [])):
                pat, meta_info = _parse_pattern(pattern)
                for src in script_src:
                    m = _safe_match(pat, src)
                    if m:
                        c = meta_info.get("confidence", 100)
                        confidence = max(confidence, c)
                        v = _extract_version(m, meta_info)
                        if v:
                            version = v

            # --- headers: regex match on response headers ---
            for header_name, pattern in (tech.get("headers") or {}).items():
                header_val = headers.get(header_name.lower(), "")
                if not header_val and not pattern:
                    continue
                if header_val:
                    pat, meta_info = _parse_pattern(pattern)
                    if not pat:
                        confidence = max(confidence, meta_info.get("confidence", 100))
                    else:
                        m = _safe_match(pat, header_val)
                        if m:
                            confidence = max(confidence, meta_info.get("confidence", 100))
                            v = _extract_version(m, meta_info)
                            if v:
                                version = v

            # --- cookies: match cookie names ---
            for cookie_name, pattern in (tech.get("cookies") or {}).items():
                if "*" in cookie_name:
                    # Wildcard cookie name (e.g., "_ga_*")
                    cookie_pat = cookie_name.replace("*", ".*")
                    for cn, cv in cookies.items():
                        if _safe_match(cookie_pat, cn):
                            pat, meta_info = _parse_pattern(pattern)
                            confidence = max(confidence, meta_info.get("confidence", 100))
                            if pat and cv:
                                m = _safe_match(pat, cv)
                                if m:
                                    v = _extract_version(m, meta_info)
                                    if v:
                                        version = v
                elif cookie_name in cookies:
                    pat, meta_info = _parse_pattern(pattern)
                    confidence = max(confidence, meta_info.get("confidence", 100))
                    if pat:
                        m = _safe_match(pat, cookies[cookie_name])
                        if m:
                            v = _extract_version(m, meta_info)
                            if v:
                                version = v

            # --- meta: match <meta> tags ---
            for meta_name, pattern in (tech.get("meta") or {}).items():
                meta_val = meta.get(meta_name.lower(), "")
                if meta_val:
                    pat, meta_info = _parse_pattern(pattern)
                    if not pat:
                        confidence = max(confidence, meta_info.get("confidence", 100))
                    else:
                        m = _safe_match(pat, meta_val)
                        if m:
                            confidence = max(confidence, meta_info.get("confidence", 100))
                            v = _extract_version(m, meta_info)
                            if v:
                                version = v

            # --- html: regex match on raw HTML ---
            for pattern in _as_list(tech.get("html", [])):
                pat, meta_info = _parse_pattern(pattern)
                m = _safe_match(pat, html)
                if m:
                    confidence = max(confidence, meta_info.get("confidence", 100))
                    v = _extract_version(m, meta_info)
                    if v:
                        version = v

            # --- scripts: regex match on inline <script> content ---
            if tech.get("scripts"):
                for pattern in _as_list(tech.get("scripts", [])):
                    pat, meta_info = _parse_pattern(pattern)
                    m = _safe_match(pat, page.script_text)
                    if m:
                        confidence = max(confidence, meta_info.get("confidence", 100))
                        v = _extract_version(m, meta_info)
                        if v:
                            version = v

            # --- css: regex match on inline <style> content ---
            if tech.get("css") and html:
                style_text = page.style_text
                if style_text:
                    for pattern in _as_list(tech.get("css", [])):
                        pat, meta_info = _parse_pattern(pattern)
                        m = _safe_match(pat, style_text)
                        if m:
                            confidence = max(confidence, meta_info.get("confidence", 100))
                            v = _extract_version(m, meta_info)
                            if v:
                                version = v

            # --- url: regex match on page URL ---
            if url and tech.get("url"):
                for pattern in _as_list(tech.get("url", [])):
                    pat, meta_info = _parse_pattern(pattern)
                    m = _safe_match(pat, url)
                    if m:
                        confidence = max(confidence, meta_info.get("confidence", 100))

            # --- js: check JavaScript global variables from browser probe ---
            if js_globals and tech.get("js"):
                for js_path, pattern in tech["js"].items():
                    value = js_globals.get(js_path)
                    if value is not None:
                        pat, meta_info = _parse_pattern(pattern)
                        c = meta_info.get("confidence", 100)
                        if pat:
                            m = _safe_match(pat, str(value))
                            if m:
                                confidence = max(confidence, c)
                                v = _extract_version(m, meta_info)
                                if v:
                                    version = v
                        else:
                            # No pattern - existence is enough
                            confidence = max(confidence, c)

            # --- dom: CSS selector presence (simplified) ---
            # Selector-only entries use the cheap whole-page heuristic
            # (_check_dom_pattern). Entries with `attributes` / `text`
            # checks run each pattern against the attribute value / text
            # of the elements the selector names, never the whole page:
            # see _match_dom_checks for why.
            if tech.get("dom") and html:
                for selector_info in _as_list(tech["dom"]):
                    if isinstance(selector_info, str):
                        if _check_dom_pattern(selector_info, html, page.lower):
                            confidence = max(confidence, 100)
                    elif isinstance(selector_info, dict):
                        for selector, checks in selector_info.items():
                            if isinstance(checks, dict):
                                if "properties" in checks:
                                    continue  # JS properties need a live DOM
                                if "attributes" in checks or "text" in checks:
                                    hit = _match_dom_checks(selector, checks, page)
                                    if hit:
                                        confidence = max(confidence, hit[0])
                                        if hit[1]:
                                            version = hit[1]
                                    continue
                            if _check_dom_pattern(selector, html, page.lower):
                                confidence = max(confidence, 100)

            # Record detection
            if confidence > 0:
                cat_ids = tech.get("cats", [])
                categories = [self._cat_name(c) for c in cat_ids]
                groups: list[str] = []
                for c in cat_ids:
                    groups.extend(self._cat_groups(c))
                groups = list(dict.fromkeys(groups))

                detections[tech_name] = Detection(
                    name=tech_name,
                    version=version,
                    confidence=min(confidence, 100),
                    categories=categories,
                    groups=groups,
                    website=tech.get("website", ""),
                    description=tech.get("description", ""),
                    saas=tech.get("saas", False),
                    pricing=tech.get("pricing", []),
                )

        # Resolve implies (if tech A detected and implies B, add B)
        resolved = set(detections.keys())
        changed = True
        while changed:
            changed = False
            for tech_name in list(resolved):
                tech = self._techs.get(tech_name, {})
                for implied in _as_list(tech.get("implies", [])):
                    impl_name, meta_info = _parse_implies(implied)
                    if impl_name in self._techs and impl_name not in resolved:
                        impl_tech = self._techs[impl_name]
                        cat_ids = impl_tech.get("cats", [])
                        detections[impl_name] = Detection(
                            name=impl_name,
                            confidence=meta_info.get("confidence", 100),
                            categories=[self._cat_name(c) for c in cat_ids],
                            groups=list(dict.fromkeys(
                                g for c in cat_ids for g in self._cat_groups(c)
                            )),
                            website=impl_tech.get("website", ""),
                            description=impl_tech.get("description", ""),
                            saas=impl_tech.get("saas", False),
                            pricing=impl_tech.get("pricing", []),
                        )
                        resolved.add(impl_name)
                        changed = True

        return sorted(detections.values(), key=lambda d: (-d.confidence, d.name))

    @property
    def tech_count(self) -> int:
        """Number of technologies in the fingerprint database."""
        self._load()
        assert self._techs is not None
        return len(self._techs)

    @property
    def category_count(self) -> int:
        """Number of categories."""
        self._load()
        assert self._categories is not None
        return len(self._categories)

    def build_js_probe(self) -> str:
        """Generate JavaScript that probes all Wappalyzer js globals.

        Returns a self-executing function that checks each dotted property
        path (e.g., 'jQuery.fn.jquery') and writes results to a hidden
        div#wap-probe as JSON. Inject via addScriptTag on CF /content endpoint.
        """
        self._load()
        assert self._techs is not None

        paths = set()
        for tech in self._techs.values():
            for path in (tech.get("js") or {}):
                paths.add(path)

        checks = []
        for path in sorted(paths):
            safe_path = path.replace("\\", "\\\\").replace("'", "\\'")
            checks.append(f"'{safe_path}':r('{safe_path}')")
        checks_str = ",".join(checks)

        return (
            "(function(){"
            "function r(p){"
            "try{"
            "var s=p.split('.'),o=window;"
            "for(var i=0;i<s.length;i++){if(o==null)return null;o=o[s[i]];}"
            "if(o===undefined)return null;"
            "if(typeof o==='string')return o.substring(0,100);"
            "if(typeof o==='number')return String(o);"
            "if(typeof o==='boolean')return String(o);"
            "if(typeof o==='function')return 'function';"
            "return'object';"
            "}catch(e){return null;}"
            "}"
            f"var d={{{checks_str}}};"
            "var el=document.createElement('div');"
            "el.id='wap-probe';"
            "el.style.display='none';"
            "el.textContent=JSON.stringify(d);"
            "document.body.appendChild(el);"
            "})();"
        )

    @property
    def js_path_count(self) -> int:
        """Number of JS property paths to probe."""
        self._load()
        assert self._techs is not None
        paths = set()
        for tech in self._techs.values():
            for path in (tech.get("js") or {}):
                paths.add(path)
        return len(paths)


# ---------------------------------------------------------------------------
# Module-level singleton (thread-safe lazy init)
# ---------------------------------------------------------------------------

_singleton: WappalyzerClient | None = None
_singleton_lock = threading.Lock()


def get_wappalyzer() -> WappalyzerClient:
    """Return a cached process-wide WappalyzerClient.

    Loads the ~3MB fingerprint dict once per process; subsequent callers
    share the same instance. Safe under concurrent crawl/scrape patterns.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = WappalyzerClient()
    return _singleton


# ---------------------------------------------------------------------------
# Pattern parsing helpers
# ---------------------------------------------------------------------------

def _parse_pattern(pattern: str) -> tuple[str, dict]:
    """Parse a Wappalyzer pattern string with optional metadata suffix.

    Patterns can have metadata suffixed with \\;key:value:
        "pattern\\;version:\\1"
        "pattern\\;confidence:50"
    """
    if not pattern:
        return "", {}

    parts = pattern.split("\\;")
    regex = parts[0]
    meta: dict = {}

    for part in parts[1:]:
        if ":" in part:
            key, _, value = part.partition(":")
            if key == "confidence":
                try:
                    meta["confidence"] = int(value)
                except ValueError:
                    pass
            elif key == "version":
                meta["version"] = value
            else:
                meta[key] = value

    return regex, meta


def _implied_name(implied: str) -> str:
    """Pull the tech name out of an `implies` entry (strip metadata suffix)."""
    if isinstance(implied, str) and "\\;" in implied:
        return implied.split("\\;", 1)[0]
    return implied if isinstance(implied, str) else ""


def _parse_implies(implied: str) -> tuple[str, dict]:
    """Parse an implies entry (tech name with optional confidence)."""
    if "\\;" in implied:
        parts = implied.split("\\;")
        name = parts[0]
        meta: dict = {}
        for part in parts[1:]:
            if ":" in part:
                k, _, v = part.partition(":")
                if k == "confidence":
                    try:
                        meta["confidence"] = int(v)
                    except ValueError:
                        pass
        return name, meta
    return implied, {}


def _safe_match(pattern: str, text: str) -> "re.Match | None":
    """Regex match with error handling (some Wappalyzer patterns are invalid)."""
    if not pattern or not text:
        return None
    try:
        return re.search(pattern, text, re.IGNORECASE)
    except re.error:
        return None


def _extract_version(match: "re.Match", meta: dict) -> str:
    """Extract version string from regex match using Wappalyzer version template."""
    version_template = meta.get("version", "")
    if not version_template or not match:
        return ""

    version = version_template
    for i in range(10):
        try:
            group_val = match.group(i + 1) or ""
        except (IndexError, re.error):
            group_val = ""
        version = version.replace(f"\\{i + 1}", group_val)

    # Clean up ternary expressions: \1?a:b
    version = re.sub(r"\\\d\?[^:]*:[^\\]*", "", version)

    return version.strip()


def _as_list(value) -> list:
    """Ensure value is a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if value:
        return [value]
    return []


def _check_dom_pattern(selector: str, html: str, html_lower: str | None = None) -> bool:
    """Simplified DOM selector check against raw HTML.

    Each `[attr op value]` condition must match somewhere in the page; they
    are NOT required to sit on the same tag (a loose heuristic, used only
    for selector-only `dom` entries; checks with patterns go through
    _match_dom_checks).

    `html_lower` enables a substring prefilter: every regex below embeds its
    value literally, so a value absent from the lowercased page cannot
    match and the ~13 ms regex scan of a 1.4 MB page is skipped. Only ASCII
    values are prefiltered: re.IGNORECASE also folds a few non-ASCII code
    points onto ASCII letters (U+212A KELVIN SIGN, U+017F LONG S), which
    str.lower() does not.
    """
    def _absent(value: str) -> bool:
        return (
            html_lower is not None and value.isascii()
            and value.lower() not in html_lower
        )

    attr_patterns = re.findall(r'\[(\w+)([*^$~|]?)=["\']([^"\']*)["\']', selector)

    if attr_patterns:
        for attr_name, operator, attr_value in attr_patterns:
            if attr_value and _absent(attr_value):
                return False
            escaped = re.escape(attr_value)
            if operator == "*":
                pattern = f'{attr_name}=["\'][^"\']*{escaped}[^"\']*["\']'
            elif operator == "^":
                pattern = f'{attr_name}=["\']\\s*{escaped}'
            elif operator == "$":
                pattern = f'{escaped}\\s*["\']'
            else:
                pattern = f'{attr_name}=["\']\\s*{escaped}\\s*["\']'
            _ = attr_name  # used in f-strings above; silence unused-warning on operator branches

            if not _safe_match(pattern, html):
                return False
        return True

    if "[" in selector and "=" not in selector:
        return False

    class_match = re.search(r'\.(\w[\w-]+)', selector)
    if class_match:
        cls = class_match.group(1)
        if len(cls) < 5 or _absent(cls):
            return False
        escaped = re.escape(cls)
        return _safe_match(f'class=["\'][^"\']*{escaped}', html) is not None

    id_match = re.search(r'#(\w[\w-]+)', selector)
    if id_match:
        if _absent(id_match.group(1)):
            return False
        id_val = re.escape(id_match.group(1))
        return _safe_match(f'id=["\'][^"\']*{id_val}', html) is not None

    return False


# ---------------------------------------------------------------------------
# DOM element matching (dom entries with `attributes` / `text` checks)
#
# Wappalyzer's `{selector: {"attributes": {attr: pattern}}}` means "an
# element matching `selector` whose `attr` matches `pattern`" (`text`: the
# element's text). The engine once ran these patterns over the whole page,
# which (1) matched text outside the element, (2) made `^`-anchored
# patterns unmatchable, (3) never extracted versions, and (4) let greedy
# patterns backtrack across the page: upstream Tailwind's
# `assets.*index\.v...` took 10 s of a 47 s analyze() on a 1.4 MB page.
#
# The page's start tags are indexed once per analyze() with regexes (no
# parser dependency: Fathom, OTDB and PHPScan's JS port mirror this code).
# Selector support is deliberately partial: only the last compound of
# each comma-separated selector is checked (tag, #id, .class, [attr],
# [attr op value]); ancestors and pseudo-classes are ignored, so matching
# is looser than a browser. An unparseable selector matches nothing.
# ---------------------------------------------------------------------------

# A start tag. Attribute text may hold '>' inside quotes. The single-char
# alternation keeps the scan linear on unterminated tags (no nested `+`).
_TAG_RE = re.compile(r"""<([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>""")
_ATTR_RE = re.compile(
    r"""([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?"""
)
_INLINE_SCRIPT_RE = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
_INLINE_STYLE_RE = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL | re.IGNORECASE)
_STRIP_TAGS_RE = re.compile(r"<[^>]*>")

# One element: (tag, {attr: value}, offset just past its start tag).
_Element = tuple[str, dict[str, str], int]


class _Page:
    """Per-analyze() views of the HTML, each derived lazily and at most once."""

    def __init__(self, html: str):
        self.html = html
        self._lower: str | None = None
        self._script_text: str | None = None
        self._style_text: str | None = None
        self._by_tag: dict[str, list[_Element]] | None = None
        self._by_attr: dict[str, list[_Element]] = {}

    @property
    def lower(self) -> str:
        if self._lower is None:
            self._lower = self.html.lower()
        return self._lower

    @property
    def script_text(self) -> str:
        if self._script_text is None:
            self._script_text = "\n".join(_INLINE_SCRIPT_RE.findall(self.html))
        return self._script_text

    @property
    def style_text(self) -> str:
        if self._style_text is None:
            self._style_text = "\n".join(_INLINE_STYLE_RE.findall(self.html))
        return self._style_text

    def _index(self) -> dict[str, list[_Element]]:
        if self._by_tag is None:
            by_tag: dict[str, list[_Element]] = {}
            by_attr: dict[str, list[_Element]] = {}
            for m in _TAG_RE.finditer(self.html):
                attrs: dict[str, str] = {}
                for a in _ATTR_RE.finditer(m.group(2)):
                    name = a.group(1).lower()
                    if name not in attrs:  # first wins, as in browsers
                        attrs[name] = next(
                            (g for g in a.group(2, 3, 4) if g is not None), ""
                        )
                el: _Element = (m.group(1).lower(), attrs, m.end())
                by_tag.setdefault(el[0], []).append(el)
                for name in attrs:
                    by_attr.setdefault(name, []).append(el)
            self._by_tag, self._by_attr = by_tag, by_attr
        return self._by_tag

    def candidates(self, compound: _Compound) -> list[_Element]:
        """Elements that could match `compound`: its tag's, else the
        rarest required attribute's (class/id included)."""
        by_tag = self._index()
        tag, ids, classes, conds = compound
        if tag:
            return by_tag.get(tag, [])
        needed = [name for name, _, _ in conds]
        if ids:
            needed.append("id")
        if classes:
            needed.append("class")
        if not needed:
            return [el for els in by_tag.values() for el in els]
        return min((self._by_attr.get(n, []) for n in needed), key=len)

    def text_of(self, el: _Element) -> str:
        """Text up to the element's first closing tag, tags stripped.

        Nested same-name children end it early; good enough for the short
        footer/badge strings `text` checks target."""
        close = re.compile(rf"</{re.escape(el[0])}\s*>", re.IGNORECASE).search(self.html, el[2])
        if close is None:
            return ""
        return _STRIP_TAGS_RE.sub("", self.html[el[2]:close.start()])


# (tag or None, ids, classes, ((attr, op, value), ...)); op "" = present.
_Compound = tuple[str | None, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, str], ...]]

_COMPOUND_PART_RE = re.compile(
    r"""\#([\w-]+)"""
    r"""|\.([\w-]+)"""
    r"""|\[\s*([\w:-]+)\s*(?:([*^$~|]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+)))?\s*(?:[iIsS]\s*)?\]"""
    r"""|::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?"""
)


def _split_top_level(s: str, seps: str) -> list[str]:
    """Split `s` on any char in `seps` outside brackets, parens and quotes."""
    out, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif depth == 0 and ch in seps:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [p.strip() for p in out if p.strip()]


@functools.lru_cache(maxsize=4096)
def _parse_selector(selector: str) -> tuple[_Compound, ...]:
    """Last compound of each comma-separated selector; () if unparseable."""
    compounds: list[_Compound] = []
    for alternative in _split_top_level(selector, ","):
        last = _split_top_level(alternative, " \t\n>+~")[-1]
        m = re.match(r"([a-zA-Z][\w-]*|\*)?", last)
        tag = (m.group(1) or "").lower() if m else ""
        pos = m.end() if m else 0
        ids: list[str] = []
        classes: list[str] = []
        conds: list[tuple[str, str, str]] = []
        while pos < len(last):
            p = _COMPOUND_PART_RE.match(last, pos)
            if not p:
                logger.debug("dom selector not understood: %r", selector)
                return ()
            if p.group(1):
                ids.append(p.group(1).lower())
            elif p.group(2):
                classes.append(p.group(2).lower())
            elif p.group(3):
                value = next((g for g in p.group(5, 6, 7) if g is not None), "")
                conds.append((p.group(3).lower(), p.group(4) or "", value.lower()))
            pos = p.end()
        compounds.append((None if tag in ("", "*") else tag, tuple(ids), tuple(classes), tuple(conds)))
    return tuple(compounds)


def _element_matches(el: _Element, compound: _Compound) -> bool:
    _, attrs, _ = el
    _, ids, classes, conds = compound
    if ids and attrs.get("id", "").lower() not in ids:
        return False
    if classes:
        have = attrs.get("class", "").lower().split()
        if any(c not in have for c in classes):
            return False
    for name, op, want in conds:
        value = attrs.get(name)
        if value is None:
            return False
        value = value.lower()  # case-insensitive, as _check_dom_pattern is
        if op == "=" and value != want:
            return False
        if op == "*=" and want not in value:
            return False
        if op == "^=" and not value.startswith(want):
            return False
        if op == "$=" and not value.endswith(want):
            return False
        if op == "~=" and want not in value.split():
            return False
        if op == "|=" and not (value == want or value.startswith(want + "-")):
            return False
    return True


def _match_dom_checks(selector: str, checks: dict, page: _Page) -> tuple[int, str] | None:
    """(confidence, version) for the first element matching `selector`
    whose text and attributes all satisfy `checks`; None if none does.

    An empty pattern means "present": the attribute must exist, any text
    passes. Confidence is the lowest declared on the satisfied patterns.
    """
    text_check = _parse_pattern(checks["text"]) if checks.get("text") else None
    attr_checks = [
        (name.lower(), *_parse_pattern(pattern))
        for name, pattern in (checks.get("attributes") or {}).items()
    ]
    for compound in _parse_selector(selector):
        for el in page.candidates(compound):
            if not _element_matches(el, compound):  # candidates() already matched the tag
                continue
            confidence, version = 100, ""
            satisfied = True
            if text_check is not None:
                pat, mi = text_check
                m = _safe_match(pat, page.text_of(el)) if pat else None
                if pat and not m:
                    continue
                confidence = min(confidence, mi.get("confidence", 100))
                version = (m and _extract_version(m, mi)) or version
            for name, pat, mi in attr_checks:
                value = el[1].get(name)
                if value is None:
                    satisfied = False
                    break
                m = _safe_match(pat, value) if pat else None
                if pat and not m:
                    satisfied = False
                    break
                confidence = min(confidence, mi.get("confidence", 100))
                version = version or (m and _extract_version(m, mi)) or ""
            if satisfied:
                return confidence, version
    return None
