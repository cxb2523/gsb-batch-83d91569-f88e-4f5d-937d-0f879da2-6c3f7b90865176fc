"""Kept so ``python main.py ...`` from the 2019 README still works.

Same as the ``ehentai-crawler`` command that ``pip install .`` puts on PATH.
"""

from ehentai_crawler.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
