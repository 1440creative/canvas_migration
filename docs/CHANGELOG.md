# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- CLI: `--steps` and `--resume` support in `scripts/run_import.py`.
- JSON run summary artifact (counts, timings, warnings, errors).
- Improved rate-limit/backoff observability in `utils/api.py`.
- Optional batching/concurrency for heavy endpoints.
- Docs for exporter/importer data shapes; sample “tiny” sandbox export.

## [0.1.0-tests-green] – 2025-09-25

### Added

- **Dry-run CLI**: `scripts/run_import.py --dry-run -v` prints a plan with per-step counts and empty id_map notice.
- **Rubrics pipeline**:
  - `export_rubrics`: writes slim `rubrics/rubrics.json` (includes `id`, `title`, `points_possible`, `criteria`, `associations`).
  - `import_rubrics`: creates rubrics and associates them via `rubric_associations`, honoring `id_map['assignments']`; updates `id_map['rubrics']`.
- **Discussions importer**: imports non-announcement topics; follows `Location` when POST lacks ID; consistent counters & logging.
- **Files importer**:
  - Deterministic placement under `course_id/files/...`.
  - Two-step upload flow helper usage; SHA-256 manifest prevents re-upload; logs “skipped upload (same sha256)”.
  - Maps old file IDs into `id_map['files']`.

### Changed

- **Pages importer**:
  - Records `id_map['pages']` (source→target ID) and `id_map['pages_url']` (slug remap).
  - Follows `Location` when POST body is missing `id`.
  - Logs `position-field-ignored` **once** per run.
- **Quizzes importer**:
  - Handles both direct `id` in POST body and `201 Location` follow-up.
  - Optional questions import; robust counters.
- **Modules importer**:
  - Simplified and made resilient to odd response shapes; standardized counters (`imported/skipped/failed/total`) plus legacy keys.
- **Course import runner** (`importers/import_course.py`):
  - Unifies counters and logging (`artifact` + `course_id`).
  - `scan_export()` produces stable per-step counts for dry-run plans.
- **utils/api.py**:
  - Pruned unused helpers; clarified `_full_url`, pagination, and multipart upload flow.
  - Safer JSON parsing helpers for POST/GET responses.

### Fixed

- Front-page PUT failure increments `failed` and logs status cleanly.
- Duplicate position warnings removed; now a single warning per run.
- Manifest-based file dedup correctly increments `skipped`.

### Tests

- Suite now green across importers (pages, assignments, quizzes, files, discussions, modules, rubrics, rubric_links, course).
- Request mocks cover POST/PUT/GET variations and failure modes.
- Dry-run CLI test asserts counts and id_map notice.

[Unreleased]: https://github.com/1440creative/canvas_migration/compare/v0.1.0-tests-green...HEAD
[0.1.0-tests-green]: https://github.com/1440creative/canvas_migration/tree/v0.1.0-tests-green
