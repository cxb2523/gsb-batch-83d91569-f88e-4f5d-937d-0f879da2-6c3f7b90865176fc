# GatherRadar Agent Instructions

@PROJECT_CONTEXT.md

`PROJECT_CONTEXT.md` is the canonical product and architecture brief. Read it
before planning or changing code.

Codex loads this file automatically from the repository root. Claude Code users
should create a root `CLAUDE.md` containing `@AGENTS.md`; this keeps one shared
instruction source and avoids duplicated rules.

## Mission and scope

- Build the smallest trustworthy event-discovery pipeline for the owner and a
  private community of roughly 20–40 people.
- Keep the current milestone focused on curated public sources through a
  reviewable local XLSX output with portable exports; Google publishing is optional.
- Do not introduce a dashboard, Telegram automation, recommendations, accounts,
  payments, multi-tenancy, or public-scale infrastructure unless the task
  explicitly changes the milestone.
- Prefer a thin vertical slice through one real source over several incomplete
  abstractions.

## Before changing anything

- Inspect the repository, active instructions, Git status, and relevant files.
- Preserve user changes and avoid unrelated formatting or refactors.
- Check `PROJECT_CONTEXT.md` for product boundaries and unresolved decisions.
- If the request depends on a decision listed as open, make a reversible
  assumption and document it. Ask only when the choice is costly, destructive,
  security-sensitive, or changes product scope.
- Never claim a source behavior, command, or test result that was not verified.

## Architecture guardrails

- Keep the pipeline boundaries explicit: source registry → adapters → raw
  observations → extraction → normalization/validation → deduplication →
  canonical storage → exports.
- Keep source-specific selectors and parsing inside their adapter.
- Keep domain records independent of scraping, AI, database, and Google clients.
- Use local SQLite canonical/review persistence behind a repository boundary.
  JSONL remains the source/evidence audit trail; XLSX is the default human review UI.
  CSV/JSON and manual Gemini bundles are exports; Google Sheets is optional.
- Make runs idempotent. Use stable IDs, source URLs/IDs, content hashes, and
  upserts so a rerun does not create duplicate rows.
- Preserve raw observations separately from canonical event candidates.
- Put AI extraction behind an interface. Validate its output before persistence
  and never treat model confidence as proof.
- Prefer deterministic code for date conversion, validation, status calculation,
  and exact duplicate checks.
- Keep external integrations replaceable and isolate their failures.

## Event data rules

- Every canonical event and material field must be traceable to source evidence.
- Preserve original date and price text alongside normalized values.
- Use timezone-aware datetimes and IANA timezone names. Do not assume Tehran when
  the source or event indicates another timezone.
- Handle Persian digits and Jalali dates explicitly; test boundary cases.
- Represent missing facts as null or unknown. Never fabricate dates, venues,
  prices, categories, or registration details.
- Group probable duplicates for review; do not silently delete them.
- Preserve human-owned sheet fields such as review status and reviewer notes
  during synchronization.

## Collection, privacy, and secrets

- Work only with public event data from owner-approved sources.
- Follow applicable terms, robots directives, rate limits, and platform rules.
- Prefer official or permitted feeds and APIs where available.
- Never bypass authentication, CAPTCHAs, access controls, or anti-bot measures.
- Do not collect private profiles, followers, comments, messages, or unrelated
  personal data.
- Keep credentials, cookies, tokens, private exports, and local databases out of
  Git. Use environment variables and committed example configuration with fake
  values.
- Sanitize fixtures and logs. Errors must not expose secrets or session data.
- Use bounded retries, clear timeouts, and per-source failure isolation.

## Implementation standards

- The project targets Python 3.11+ with `pip` and a local `.venv`, packaged by
  setuptools through `pyproject.toml`. No formatter, linter, or AI provider is
  selected yet. Do not introduce them as a side effect of an unrelated task.
- Setup and run commands:

  ```bash
  python -m venv .venv
  python -m pip install -e .
  python -m unittest discover -s tests
  python -m gatherradar collect instagram davvvat_instagram --limit 5
  ```
- Use type hints at public boundaries and small modules with one responsibility.
- Validate untrusted network, extractor, configuration, and spreadsheet data at
  system boundaries.
- Keep configuration declarative and separate from source adapter code.
- Use structured, secret-safe logging with a `run_id` and source context.
- Add a dependency only when the standard library or an existing dependency does
  not reasonably solve the need; record architecture-significant choices.
- Avoid speculative abstractions. Extract a shared abstraction after a second
  concrete use demonstrates it.

## Testing and verification

- Run the suite with `python -m unittest discover -s tests`. It is offline and must
  stay that way; live collection happens only through an explicit CLI command.
- Test deterministic normalization and validation with unit tests.
- Test collectors and extractors against small, sanitized, versioned fixtures.
- Include Persian digits, Jalali/Gregorian conversion, timezone, missing-field,
  malformed-content, and duplicate cases where relevant.
- Default tests must not depend on live websites, Instagram, paid AI calls, or a
  real Google Sheet.
- Put live-source and integration checks behind explicit opt-in markers or
  commands.
- Verify migrations and sheet synchronization are idempotent and preserve
  reviewer-owned fields.
- Calibrate verification to the change. Documentation-only edits require link,
  structure, and diff review rather than an invented application test suite.

## Working procedure

1. Inspect the current tree, instructions, and Git diff.
2. Restate the smallest deliverable and identify affected pipeline boundaries.
3. Implement the narrowest coherent change.
4. Add or update meaningful tests and fixtures when behavior changes.
5. Run the documented checks that apply to the changed area.
6. Review the final diff for scope, secrets, provenance, and data-contract drift.
7. Update `PROJECT_CONTEXT.md` when product scope, architecture, or the event
   contract changes.

## Git and documentation

- Keep commits single-purpose and use imperative commit messages.
- Do not rewrite history, discard local changes, force-push, or commit secrets.
- Do not commit runtime data, downloaded pages, private exports, or credentials.
- Update docs in the same change when setup, behavior, schemas, or commands
  change.
- Treat `PROJECT_CONTEXT.md` as a living decision boundary, not a backlog. Put
  task-specific plans and temporary notes elsewhere when those files exist.

## Definition of done

A change is complete when it stays within the requested scope, preserves source
provenance and human review, handles failures safely, includes proportionate
verification, passes all documented applicable checks, contains no secrets or
unrelated edits, and leaves the repository documentation accurate.
