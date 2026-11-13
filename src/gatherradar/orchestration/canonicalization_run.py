"""Read one local snapshot per source, discover, normalize, then canonicalize."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_sources
from ..deduplication import CandidateContext, CanonicalizationResult, canonicalize
from ..domain import DiscoveryUnit, EvidenceKind, RawItem, Source, SourceType
from ..extraction import DiscoveryService, RuleBasedDiscoveryProvider
from ..storage import JsonlEvidenceStore, JsonlRawItemStore
from .collection_run import instagram_output_path
from .discovery_run import run_discovery, select_latest
from .evidence_discovery_run import run_evidence_discovery
from .evidence_paths import instagram_evidence_output_path
from .normalization_run import run_normalization
from .website_run import website_output_path


@dataclass(frozen=True, slots=True)
class SourceReview:
    source: Source
    path_used: str
    raw_items: int = 0
    event_candidates: int = 0
    place_candidates: int = 0
    diagnostics: tuple[str, ...] = ()
    observed_item_ids: tuple[str, ...] = ()
    funnel: dict[str, int] = field(default_factory=dict)
    investigations: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalReview:
    result: CanonicalizationResult
    sources: tuple[SourceReview, ...]


def identity_slot(unit: DiscoveryUnit | None) -> str:
    if unit is not None:
        segmented = next((f for f in unit.fragments if f.extraction_engine == 'caption-segmentation'), None)
        if segmented is not None:
            index = segmented.extraction_config.split(';', 1)[0].split('=', 1)[1]
            return 'primary' if index == '0' else 'caption:' + index
    if unit is None or any(f.kind in {EvidenceKind.CAPTION, EvidenceKind.WEBSITE_TEXT, EvidenceKind.WEBSITE_LISTING}
                           for f in unit.fragments):
        return "primary"
    # Stage 5 orders fragments deterministically by kind/position. Using the
    # first slot keeps an edit to its content from changing occurrence identity.
    fragment = unit.fragments[0]
    position = fragment.slide_index if fragment.kind is EvidenceKind.CAROUSEL_SLIDE_OCR else fragment.frame_timestamp_ms
    return f"{fragment.kind.value}:{position if position is not None else 'single'}"


def run_canonical_review(
    source_ids: Sequence[str] = (), *, all_enabled: bool = False,
    config_path: str | Path = "config/sources.yaml", data_dir: str | Path = "data",
    limit: int = 5, instagram_evidence: bool = False,
    observed_items: dict[str, tuple[RawItem, ...]] | None = None,
) -> CanonicalReview:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise ValueError("limit must be between 1 and 30 per source")
    if bool(source_ids) == all_enabled:
        raise ValueError("select source IDs or all_enabled, exclusively")
    sources = load_sources(config_path)
    known = {s.id for s in sources}
    if set(source_ids) - known:
        raise ValueError("unknown source selection")
    selected = sorted((s for s in sources if (s.enabled if all_enabled else s.id in source_ids)), key=lambda s: s.id)
    contexts, reports = [], []
    service = DiscoveryService(RuleBasedDiscoveryProvider())
    for source in selected:
        try:
            path = (website_output_path(source, data_dir) if source.source_type is SourceType.WEBSITE
                    else instagram_output_path(source, data_dir))
            stored = JsonlRawItemStore(path).read_latest_items()
            diagnostics = [f"raw:{reason.split(':', 1)[0]}:invalid_record" for reason in stored.malformed]
            items = tuple(item for item in stored.items if item.source_id == source.id and item.source_type == source.source_type)
            if len(items) != len(stored.items):
                diagnostics.append("raw:context_mismatch")
            if observed_items is None:
                items = items[:limit] if source.source_type is SourceType.WEBSITE else select_latest(items, limit)
            else:
                items = observed_items.get(source.id, ())
                # A website channel may also hold up to `limit` approved linked
                # detail pages named by another channel this run.
                bound = limit * 2 if source.source_type is SourceType.WEBSITE else limit
                if (len(items) > bound or len({i.id for i in items}) != len(items)
                        or any(i.source_id != source.id or i.source_type != source.source_type for i in items)):
                    raise ValueError("invalid current-run membership")
            if not items:
                reports.append(SourceReview(source, "no_local_data", diagnostics=tuple(diagnostics)))
                continue
            history = ()
            if source.source_type is SourceType.INSTAGRAM and instagram_evidence:
                evidence = JsonlEvidenceStore(instagram_evidence_output_path(source, data_dir)).read()
                history = evidence.fragments
                diagnostics.extend(f"evidence:{reason.split(':', 1)[0]}:invalid_record" for reason in evidence.malformed)
            # Evidence opt-in always uses Stage 5 for this source. Its primary
            # fragment is the caption fallback, including items without media.
            use_units = source.source_type is SourceType.WEBSITE or instagram_evidence
            if use_units:
                summary = run_evidence_discovery(items, history, service, sources={source.id: source})
                units = {unit.unit_id: unit for item in summary.items for unit in item.units}
                if source.source_type is SourceType.WEBSITE:
                    mode = "website_text"
                else:
                    used_media = any(f.kind not in {EvidenceKind.CAPTION, EvidenceKind.WEBSITE_TEXT, EvidenceKind.WEBSITE_LISTING}
                                     for unit in units.values() for f in unit.fragments + unit.collapsed)
                    mode = "evidence_with_caption_fallback" if used_media else "caption_fallback"
            else:
                summary = run_discovery(items, service, sources={source.id: source})
                units = {}
                mode = "caption_only"
            if summary.failed:
                diagnostics.append(f"discovery_failed:{summary.failed}")
            raw_map = {item.id: item for item in items}
            normalized = run_normalization(summary.outcomes, raw_map, {source.id: source},
                                           unit_texts={key: unit.text for key, unit in units.items()})
            discoveries = [o for o in summary.outcomes if o.candidate is not None]
            first_seen = dict(stored.first_seen_at)
            source_contexts = []
            for outcome, discovery in zip(normalized, discoveries):
                raw = raw_map[outcome.candidate.raw_item_id]
                source_contexts.append(CandidateContext(outcome, discovery.candidate, raw, source,
                    first_seen.get(raw.id, raw.captured_at), identity_slot(units.get(discovery.discovery_unit_id))))
            contexts.extend(source_contexts)
            by_raw = {raw.id: [o for o in summary.outcomes if o.raw_item_id == raw.id] for raw in items}
            event_items = {key for key, values in by_raw.items() if any(o.event for o in values)}
            non_event = {key for key, values in by_raw.items() if key not in event_items
                         and any(o.evidence and (o.evidence.reason or '').startswith('non_event:') for o in values)}
            investigations = tuple(dict(raw_item_id=raw.id, url=raw.content_url,
                reason='title_resolution_failed' if outcome.event and not outcome.event.title else reason)
                for raw in items for outcome in by_raw[raw.id]
                if (reason := outcome.evidence.reason if outcome.evidence else outcome.reason)
                and (reason.startswith(('needs_evidence:', 'non_event:')) or outcome.event and not outcome.event.title))
            candidates = summary.event_candidates
            funnel = dict(raw_items_selected=len(items), likely_event_items=len(event_items),
                confirmed_non_event_items=len(non_event), unclassified_items=len(items)-len(event_items)-len(non_event),
                event_candidates=len(candidates), explicit_titles_found=sum(bool(c.display_title_origin and
                    c.display_title_origin.startswith('explicit_')) for c in candidates),
                descriptive_titles_recovered=sum(c.display_title_origin == 'derived_from_source_description' for c in candidates),
                unresolved_titles=sum(not c.title for c in candidates),
                occurrences_resolved=sum(len(c.outcome.candidate.occurrences) for c in source_contexts
                                         if hasattr(c.outcome.candidate, 'occurrences')),
                evidence_fragments=len({f.fragment_id for u in units.values() for f in u.fragments + u.collapsed}),
                media_ocr_failures=sum(bool(f.failure_reason) for f in history if f.raw_item_id in by_raw))
            reports.append(SourceReview(source, mode, len(items), summary.events, summary.places,
                                        tuple(diagnostics), tuple(sorted(item.id for item in items)), funnel, investigations))
        except Exception:
            # Never echo an exception that could contain source payloads or secrets.
            reports.append(SourceReview(source, "source_failed", diagnostics=("offline_source_failed",)))
    return CanonicalReview(canonicalize(contexts), tuple(reports))
