# Contributing

## Setup

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests need no API key and make no network requests, except that tiktoken downloads its `cl100k_base` encoding the first time it runs on a machine.

## Recorded Jev responses

`tests/test_end_to_end.py` replays the Jev responses recorded in `tests/fixtures/e2e/jev`, keyed by the hash of each request. A change that alters what is sent to Jev, such as extraction, prompts, or windowing, makes the test fail with "no recorded Jev response". Re-recording needs a TypeSafe API key:

```bash
JEVFETCH_RECORD=1 uv run pytest tests/test_end_to_end.py
```

If you have no key, open the pull request with the failing test and say so in the description; a maintainer re-records and adds the fixtures to the branch.

## Pull requests

Pull requests are squash-merged, so the pull request title becomes the commit on `main` and the commits on your branch do not. Write the title as one line in the form `type: description`, with type one of feat, fix, docs, refactor, test, chore. Details belong in the pull request description.
