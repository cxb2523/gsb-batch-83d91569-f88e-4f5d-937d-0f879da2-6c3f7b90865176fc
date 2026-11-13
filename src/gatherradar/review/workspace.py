"""Coordinate disposable outputs after persistence; isolate individual failures."""
from __future__ import annotations

from pathlib import Path

from .models import CanonicalRepository, ReviewError, ReviewExporter


class ReviewWorkspace:
    def __init__(self, repository: CanonicalRepository, workbook: str | Path,
                 exporters: tuple[ReviewExporter, ...]) -> None:
        self.repository, self.workbook, self.exporters = repository, Path(workbook), exporters
        self.hold_workbook = False

    def import_reviews(self):
        from ..exports.excel import ExcelReviewImporter
        result = ExcelReviewImporter(self.workbook, self.repository).import_reviews()
        self.hold_workbook = bool(result.malformed or result.conflicts)
        return result

    def export(self, run_id: str) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        document = self.repository.load(run_id)
        paths, failures = [], []
        for exporter in self.exporters:
            name = type(exporter).__name__
            if self.hold_workbook and name == 'ExcelReviewExporter':
                failures.append('XLSX preserved: resolve malformed/conflicting review rows before retrying export.')
                continue
            try:
                paths.extend(exporter.export(document))
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ReviewError) else 'write failed; inspect output path and retry offline export'
                failures.append(f'{name}: {reason}')
        return tuple(paths), tuple(failures)


def local_workspace(repository: CanonicalRepository, workbook: Path, export_dir: Path,
                    kind: str = 'all') -> ReviewWorkspace:
    exporters = []
    if kind in ('all', 'xlsx'):
        from ..exports.excel import ExcelReviewExporter
        exporters.append(ExcelReviewExporter(workbook, repository))
    if kind in ('all', 'csv'):
        from ..exports.portable import CsvReviewExporter
        exporters.append(CsvReviewExporter(export_dir))
    if kind in ('all', 'json'):
        from ..exports.portable import JsonReviewExporter
        exporters.append(JsonReviewExporter(export_dir))
    if kind in ('all', 'gemini'):
        from ..exports.gemini import GeminiBundleExporter
        exporters.append(GeminiBundleExporter(export_dir / 'gemini'))
    return ReviewWorkspace(repository, workbook, tuple(exporters))
