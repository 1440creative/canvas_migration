# Canvas Migration Toolkit

This project provides a full export/import pipeline for Canvas LMS courses.

---

## Quickstart

The fastest way to confirm everything works is to run a **dry-run** against the included sample data.

### 1. Clone and install

```bash
git clone git@github.com:1440creative/canvas_migration.git
cd canvas_migration
pip install -r requirements.txt
```

### 2. Set up environment

Create a `.env` file with dummy values (just to satisfy `utils/api.py` import-time checks):

```bash
echo "CANVAS_SOURCE_URL=https://source.example.edu" >> .env
echo "CANVAS_SOURCE_TOKEN=dummy" >> .env
echo "CANVAS_TARGET_URL=https://target.example.edu" >> .env
echo "CANVAS_TARGET_TOKEN=dummy" >> .env
```

### 3. Run a dry-run

```bash
python scripts/run_import.py \
  --export-root sandbox_export/data/901 \
  --target-course-id 999 \
  --dry-run -v
```

Expected output (truncated):

```text
DRY-RUN: plan for steps
 - pages: 1 item(s)
 - assignments: 1 item(s)
 - quizzes: 1 item(s)
 - files: 1 item(s)
 - discussions: 1 item(s)
 - modules: 0 item(s)
 - rubrics: 0 item(s)
 - rubric_links: 0 item(s)
 - course: 1 item(s)
id_map keys present: none
```

---

## Import pipeline

**Order:**

1. pages
2. assignment groups
3. assignments
4. quizzes (optionally questions)
5. files
6. discussions
7. announcements
8. modules
9. course settings (optionally blueprint sync)

---

## Environment variables

Required by `utils/api.py`:

```
CANVAS_SOURCE_URL=
CANVAS_SOURCE_TOKEN=
CANVAS_TARGET_URL=
CANVAS_TARGET_TOKEN=
```

---

## Real run

```bash
python scripts/run_import.py \
  --export-root export/data/<SOURCE_ID> \
  --target-account-id <ACCOUNT_ID> \
  --target-course-id <TARGET_ID> \
  --blueprint-sync \
  -vv
```
Blueprint status is exported so you can review the original course configuration, but enabling or managing blueprints in the target account still requires a manual step.

After a successful run the importer automatically rewrites page and assignment HTML so links to the source course (files, assignments, quizzes, discussions, modules, pages) are updated to the new target IDs using the generated `id_map.json`. No manual link cleanup is required as long as pages, assignments, files, quizzes, discussions, and modules are included in the import.

### Standalone HTML post-processing

If you need to clean up HTML outside the full importer (e.g. running a transform step between export and import, or correcting content after a partial import), run the post-processor directly against the export directory:

```bash
python scripts/postprocess_html.py \
  export/data/77275 \
  --target-course-id 12345
```

- The script reads `id_map.json` from the export root unless you override it with `--id-map`.
- `--source-course-id` overrides auto-detection when the export directory name and `course/course_metadata.json` do not contain the original id.
- Pass `--dry-run` to list which files would change without rewriting them; add `--extra-html path/to/file.html` (repeatable) to include additional files that live outside the export tree.

Re-run the script after any new importer step that updates `id_map.json` so downstream HTML stays aligned with the latest mappings.

When targeting a course that lives under a non-default account (or when the existing course metadata is incomplete), pass `--target-account-id` so the importer can resolve enrollment terms and settings against the correct Canvas account. If you omit `--target-course-id` the script will automatically create a new Canvas course under the supplied account using the exported course metadata to seed the name, then continue with the import steps.

By default the importer also assigns the target course to the 'Default' enrollment term and sets participation to Course (restricts enrollments to course dates). Use `--term-name`, `--term-id`, `--no-auto-term`, or `--participation term|inherit` when running `scripts/run_import.py` if you need different behaviour (`--no-course-dates` remains as a shorthand for `--participation term`).

By default the importer clears SIS identifiers (sis_course_id, integration_id, sis_import_id). You can set new values with `--sis-course-id`, `--integration-id`, or `--sis-import-id` when running `scripts/run_import.py`.

Course hero images are remapped automatically when the original image file was exported and imported—the importer uses `id_map.json` to swap the old image file id for the new one before issuing the final course settings update.
so links to the source course (files, assignments, quizzes, discussions, modules, pages) are updated to the new target IDs using the generated `id_map.json`. No manual link cleanup is required as long as pages, assignments, files, quizzes, discussions, and modules are included in the import.

When the source course relies on a custom grading scheme, create the matching scheme in the target account before importing and add its Canvas id to `id_map.json` under `grading_standards` (for example: `"grading_standards": {"17642": 90210}`). If no mapping exists the importer will create a course-scoped copy during the settings step.

Quiz question payloads are now exported and imported by default. Use `--skip-questions` with `scripts/run_export.py` or `--skip-quiz-questions` with `scripts/run_import.py` if you need to opt out for troubleshooting.

---

## Batch automation

Use `scripts/batch_export.py` to collect courses flagged as ready in the coordination workbook. Successful exports log course ids to `docs/exported_course_ids.txt` (configurable) so you can track which bundles are ready to import.

After exports finish, run `scripts/batch_import.py` to import each bundle into a target Canvas account. The importer creates courses automatically under the specified account unless you append extra arguments (e.g., `--target-course-id`) via `--extra-import-args`. Use `--course-prefix`, `--course-ids`, or `--course-id-file` when you need to limit a run to a subset of exports, and `--record-reset` if you want a fresh record file per batch.

Example:

```bash
python scripts/batch_import.py \
  --export-root export/data \
  --target-account-id 135 \
  --summary-dir docs/import_summaries \
  --record-path docs/imported_courses.txt \
  --course-prefix CITY \
  --record-reset \
  --include-quiz-questions \
  -vv --extra-import-args -- --participation course
```

`--summary-dir` writes `import_summary_<course>.json` files mirroring the single-course importer, and `--record-path` appends a TSV row per run (`source_id`, `course_name`, `summary_filename`) to simplify downstream auditing.

---

## Timestamp Handling (\*\_at fields)

All metadata dataclasses (e.g., `PageMeta`, `ModuleMeta`, `AssignmentMeta`, `QuizMeta`) normalize Canvas API timestamps automatically at construction time.

### Policy

**Input format**  
Canvas returns ISO-8601 strings, sometimes with offsets (e.g. `2025-08-19T10:52:51-07:00`), sometimes with `Z` suffix (`…T17:52:51Z`), occasionally with fractional seconds.  
Importers may also pass through API JSON without modification.

**Normalization**  
On init, each dataclass calls `utils.dates.normalize_iso8601()`:

- Converts to UTC
- Drops microseconds (second precision only)
- Always emits `Z` suffix (e.g., `2025-08-19T17:52:51Z`)
- If a timestamp is `None`, it stays `None`
- If a timestamp is naive (no timezone), assume UTC

**Storage format**  
Always stored as `str` in the form:

```
YYYY-MM-DDTHH:MM:SSZ
```

**Rationale**  
Canvas course instances may run in different local timezones.  
Normalizing to UTC `Z` avoids ambiguous “local midnight” bugs during migrations.  
Dropping microseconds makes metadata diffs stable.
