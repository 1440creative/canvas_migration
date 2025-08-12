# WIP — logging_setup branch

https://chatgpt.com/g/g-p-6896214e0c748191854e9f9cf3125473-canvas-lms-migration-refactor-cloud-import-ready/c/68962178-5208-8331-9056-4898c07a7fe7

## Current branch

refactor/logging-setup

## Last commit

[wip(logging): draft logging_setup.py (to review line-by-line later)]

## Status

- logging_setup.py exists with draft LoggerAdapter code
- Needs line-by-line review next session
- utils/logging.py renamed to utils/logger.py ✅

## Next steps

1. Review logging_setup.py line by line.
2. Commit finalized version (or amend WIP commit).
3. Add FS + string helpers into utils/fs.py and utils/strings.py (as per ChatGPT instructions).
4. Stage and commit utils changes separately.

###### Aug 11

## Current branch

`refactor/logging-setup`

## What’s done

- `export_pages.py`: deterministic export, metadata with `module_item_ids` placeholder
- `export_modules.py`: deterministic export, backfills module_item_ids for pages + assignments/files/quizzes/discussions
- Tests:
  - `test_export_modules_refactor.py` (page backfill)
  - `test_export_modules_backfill_multi.py` (page + assignment)

## Next steps

- Refactor `export_assignments.py`, `export_files.py`, `export_quizzes.py`, `export_discussions.py` to write metadata files compatible with `_backfill_by_id`.
- Confirm exporters handle logging via `get_logger`.
- Run full export on test course → verify output folder structure and metadata completeness.

## Notes

- Endpoints now omit `/api/v1` — handled by `CanvasAPI._full_url`.
- Keep `.env` URLs flexible (with or without `/api/v1`).
- All metadata JSON must be stable/deterministic for git diffs and re-imports.

## Next step

- Implement `export_quizzes.py` similar to assignments
  - Calls `courses/{course_id}/quizzes`
  - Writes `quiz_metadata.json` with `"id": <quiz_id>` for module backfill
  - Deterministic sort by position, title, id
  - Optional: include quiz questions

Current branch: `refactor/logging-setup`

## Quizzes exporter

- Endpoints: `courses/{course_id}/quizzes`, `courses/{course_id}/quizzes/{id}`, optional `.../{id}/questions`
- Writes:
  - `quizzes/{NNN}_{slug}/index.html` from `description`
  - `quizzes/{NNN}_{slug}/quiz_metadata.json` with `id`, `title`, `position`, `published`, quiz attrs, `module_item_ids`
  - Optional `questions.json` (deterministic order)
- Modules backfill will populate `module_item_ids` for quizzes via `content_id` = quiz id

## CLI

- `python -m scripts.run_export_all -c <id> [-o export/data] [--questions] [-v 0|1|2]`
- Slice flags: `--only-settings|pages|assignments|quizzes|files|discussions|modules|blueprint`

## Tests added

- settings: writes course_metadata.json + course_settings.json
- blueprint: detects blueprint, saves template+restrictions+associated_courses
