"""Offline fixture copy of the repository source registry.

The shipped registry disables `davvvat_website` because its robots.txt disallows
GatherRadar. Offline tests still exercise that adapter against sanitized fixtures,
so they read this copy, which differs only by re-enabling that one source.
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

REPO_CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'sources.yaml'
_DISABLED = '    enabled: false\n'


def _fixture_config() -> Path:
    text = REPO_CONFIG.read_text(encoding='utf-8')
    start = text.index('  - id: davvvat_website\n')
    end = text.index('  - id: ', start + 1)
    block = text[start:end]
    if block.count(_DISABLED) != 1:
        raise AssertionError('davvvat_website is expected to be disabled in the shipped registry')
    directory = Path(tempfile.mkdtemp(prefix='gatherradar-config-'))
    atexit.register(shutil.rmtree, directory, True)
    path = directory / 'sources.yaml'
    path.write_text(text[:start] + block.replace(_DISABLED, '    enabled: true\n').replace('    disabled_reason: robots\n', '')
                    + text[end:], encoding='utf-8')
    return path


FIXTURE_CONFIG = _fixture_config()
