from pathlib import Path

from ..domain import Source


def instagram_evidence_output_path(source: Source, data_dir: str | Path) -> Path:
    username = (source.username or source.id).strip().lower()
    return Path(data_dir) / 'evidence' / 'instagram' / f'{username}.jsonl'
