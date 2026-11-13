# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `--fetch-report` CLI option writing a per-URL fetch outcome CSV (`url`, `status`,
  `detail`). Each candidate URL gets exactly one row in deduped candidate order.
- `FetchStatus`/`FetchOutcome` model types and `fetch_detailed` on `RequestsFetcher`
  and `SeleniumFetcher` to distinguish success, robots.txt blocks, request
  failures/empty responses, and unsupported URLs. The string-returning `fetch`
  contract is preserved.
- Per-URL failure isolation in both threaded Requests mode and single-threaded
  Selenium mode; one failing URL no longer affects the remaining candidates.

## [1.0.0] - 2026-02-23

### Added

- Modular `src/email_harvester` package architecture.
- Installable CLI entrypoint `email-harvester`.
- Deterministic pytest suite with coverage gate.
- Ruff, mypy, pre-commit, Docker, Makefile, and CI workflow.
- Governance and security docs (`LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`).

### Changed

- Replaced monolithic script internals with package modules.
- Preserved backward compatibility via wrapper `email_harvester_ultimate.py`.
- Rewrote README for complete onboarding, usage, and maintenance guidance.

### Removed

- Tracked generated output CSV from repository source control.

