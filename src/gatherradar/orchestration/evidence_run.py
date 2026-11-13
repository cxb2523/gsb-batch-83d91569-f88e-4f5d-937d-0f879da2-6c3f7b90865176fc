from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from ..collectors.instagram import DEFAULT_LIMIT
from ..collectors.base import SourceDisabledError, SourceTypeMismatchError
from ..collectors.instagram_evidence import (
    DEFAULT_MAX_CAROUSEL_SLIDES, DEFAULT_MAX_REEL_FRAMES,
    InstagramMediaEvidenceAcquirer, MediaCaptureResult,
)
from ..domain import (
    EvidenceFragment, EvidenceKind, MediaArtifact, MediaKind, RawItem, Source, SourceType,
    caption_fragment,
)
from ..ocr.quality import assess_text
from ..ocr import OcrProvider, OcrResult, OcrStatus, build_ocr_provider
from ..storage import JsonlEvidenceStore, JsonlRawItemStore, MediaArtifactStore
from .collection_run import find_source, instagram_output_path
from .discovery_run import select_latest
from .evidence_paths import instagram_evidence_output_path


@dataclass(frozen=True, slots=True)
class EvidenceRunSummary:
    run_id: str
    source: Source
    raw_items: int
    image_assets: int
    carousel_slides: int
    reel_frames: int
    ocr_succeeded: int
    ocr_empty: int
    ocr_failed: int
    new_evidence: int
    existing_evidence: int
    output_path: Path
    failures: tuple[str, ...] = ()
    malformed: tuple[str, ...] = ()
    capture_failed_slides: int = 0
    capture_diagnostics: tuple[dict, ...] = ()
    # Engines that could run, engines skipped as unavailable (names only), and
    # artifacts for which a later engine was tried after unusable output.
    ocr_engines: tuple[str, ...] = ()
    ocr_unavailable: tuple[str, ...] = ()
    ocr_fallback_used: int = 0
    # Artifacts where nonempty but implausible text sent OCR to another engine.
    ocr_quality_retries: int = 0


def _evidence_kind(kind: MediaKind) -> EvidenceKind:
    return {
        MediaKind.IMAGE: EvidenceKind.IMAGE_OCR,
        MediaKind.CAROUSEL_SLIDE: EvidenceKind.CAROUSEL_SLIDE_OCR,
        MediaKind.REEL_FRAME: EvidenceKind.REEL_FRAME_OCR,
    }[kind]


def fragment_from_ocr(artifact: MediaArtifact, result: OcrResult) -> EvidenceFragment:
    return EvidenceFragment.create(
        raw_item_id=artifact.raw_item_id, kind=_evidence_kind(artifact.kind),
        text=result.text, raw_text=result.raw_text, source_url=artifact.source_url,
        local_asset_path=artifact.local_path, asset_hash=artifact.asset_hash,
        slide_index=artifact.slide_index, frame_timestamp_ms=artifact.frame_timestamp_ms,
        extraction_engine=result.engine, extraction_version=result.engine_version,
        extraction_config=result.config, failure_reason=result.failure_reason,
    )


def run_instagram_evidence(
    source_id: str, *, config_path: str | Path = 'config/sources.yaml',
    data_dir: str | Path = 'data', limit: int = DEFAULT_LIMIT,
    max_carousel_slides: int = DEFAULT_MAX_CAROUSEL_SLIDES,
    max_reel_frames: int = DEFAULT_MAX_REEL_FRAMES,
    acquirer: object | None = None, ocr_provider: OcrProvider | None = None,
    observed_items: tuple[RawItem, ...] | None = None,
) -> EvidenceRunSummary:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('limit must be a positive integer')
    if max_carousel_slides < 1 or max_reel_frames < 1:
        raise ValueError('media capture limits must be positive integers')
    source = find_source(source_id, config_path)
    if source.source_type is not SourceType.INSTAGRAM:
        raise SourceTypeMismatchError(f'source {source.id} is not an Instagram source')
    if not source.enabled:
        raise SourceDisabledError(f'source {source.id} is disabled in the registry')
    raw_store = JsonlRawItemStore(instagram_output_path(source, data_dir))
    raw_read = raw_store.read_latest_items()
    items = select_latest(raw_read.items, limit) if observed_items is None else observed_items
    if (len(items) > limit or len({i.id for i in items}) != len(items)
            or any(i.source_id != source.id or i.source_type is not SourceType.INSTAGRAM for i in items)):
        raise ValueError('invalid evidence run membership')
    provider = ocr_provider or build_ocr_provider()
    if items:
        provider.validate()
    # Cache by image content and slot plus the engine/version/config that read
    # it. The latest stored reading is reused when it is usable under the
    # current quality policy, or when every available engine has already read
    # this image. Installing another engine or a new policy therefore never
    # leaves an old empty or garbled reading permanently in place.
    chained = hasattr(provider, 'recognize_all')
    engines = {(getattr(p, 'name', None), getattr(p, 'version', None), getattr(p, 'config', None))
               for p in getattr(provider, 'available', (provider,))}

    media_store = MediaArtifactStore(
        data_dir, 'instagram', source.username or source.id
    )
    active_acquirer = acquirer or InstagramMediaEvidenceAcquirer(
        data_dir=data_dir, max_carousel_slides=max_carousel_slides,
        max_reel_frames=max_reel_frames,
    )
    capture = (
        active_acquirer.acquire(items, source, media_store)
        if items else MediaCaptureResult()
    )

    fragments = [caption_fragment(item) for item in items]
    succeeded = empty = failed = fallback_used = quality_retries = 0
    failures = [failure.report() for failure in capture.failures]
    evidence_store = JsonlEvidenceStore(instagram_evidence_output_path(source, data_dir))
    prior_read = evidence_store.read()
    for artifact in capture.artifacts:
        prior = [f for f in reversed(prior_read.fragments)
                 if f.raw_item_id == artifact.raw_item_id and f.asset_hash == artifact.asset_hash
                 and f.kind == _evidence_kind(artifact.kind) and f.slide_index == artifact.slide_index
                 and f.frame_timestamp_ms == artifact.frame_timestamp_ms]
        tried = {(f.extraction_engine, f.extraction_version, f.extraction_config)
                 for f in prior if not f.failure_reason} & engines
        usable = [f for f in prior if not f.failure_reason and f.text and assess_text(f.text).usable
                  and (f.extraction_engine, f.extraction_version, f.extraction_config) in engines]
        latest = prior[0] if prior else None
        versioned = all(key[1] is not None for key in engines)
        if not chained:
            cached = latest if (versioned and latest is not None and not latest.failure_reason
                                and (latest.extraction_engine, latest.extraction_version,
                                     latest.extraction_config) in engines) else None
        else:
            cached = (usable[0] if usable else latest if engines <= tried else None) if versioned else None
        if cached is not None:
            fragments.append(cached)
            succeeded += bool(cached.text)
            empty += not bool(cached.text)
            continue
        try:
            attempts = (provider.recognize_all(artifact.local_path, skip=frozenset(tried)) if chained
                        else (provider.recognize(artifact.local_path),))
        except Exception as exc:
            attempts = (OcrResult(
                status=OcrStatus.FAILED, raw_text='', text='',
                engine=getattr(provider, 'name', 'unknown'), engine_version='unknown',
                config=str(getattr(provider, 'config', 'unknown')),
                failure_reason=f'OCR failed ({type(exc).__name__})',
            ),)
        if not attempts:  # defensive: every engine already read this image
            continue
        # Every engine's attempt stays separate evidence; the chosen one is
        # appended last. Selection prefers a usable reading of the same image.
        fragments.extend(fragment_from_ocr(artifact, attempt) for attempt in attempts[:-1])
        if len(attempts) > 1 or tried:
            fallback_used += 1
            quality_retries += (any(a.meaningful and not assess_text(a.text).usable for a in attempts[:-1])
                                or any(f.text and not assess_text(f.text).usable for f in prior))
        result = attempts[-1]
        if result.status is OcrStatus.SUCCEEDED:
            succeeded += 1
        elif result.status is OcrStatus.EMPTY:
            empty += 1
        else:
            failed += 1
            failures.append(result.failure_reason or 'OCR failed')
        fragments.append(fragment_from_ocr(artifact, result))

    stored = evidence_store.append_new(fragments)
    return EvidenceRunSummary(
        run_id=uuid.uuid4().hex[:12], source=source, raw_items=len(items),
        image_assets=capture.images, carousel_slides=capture.carousel_slides,
        reel_frames=capture.reel_frames, ocr_succeeded=succeeded,
        ocr_empty=empty, ocr_failed=failed, new_evidence=stored.new,
        existing_evidence=stored.already_existing, output_path=stored.path,
        failures=tuple(failures),
        malformed=tuple((*raw_read.malformed, *prior_read.malformed)),
        capture_failed_slides=sum(f.slide_index is not None for f in capture.failures),
        capture_diagnostics=tuple(dict(source_id=source.id, raw_item_id=f.raw_item_id,
            slide_index=f.slide_index, category=f.category, retry_count=f.retry_count,
            frame_timestamp_ms=f.frame_timestamp_ms)
            for f in capture.failures),
        ocr_engines=tuple(p.name for p in getattr(provider, 'available', (provider,))),
        ocr_unavailable=tuple(sorted(getattr(provider, 'unavailable', {}))),
        ocr_fallback_used=fallback_used, ocr_quality_retries=quality_retries,
    )


__all__ = [
    'EvidenceRunSummary', 'fragment_from_ocr', 'instagram_evidence_output_path',
    'run_instagram_evidence',
]
