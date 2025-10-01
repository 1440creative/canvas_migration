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
2. assignments
3. quizzes (optionally questions)
4. files
5. discussions
6. announcements
7. modules
8. course settings (optionally blueprint sync)

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
  --target-course-id <TARGET_ID> \
  --include-quiz-questions \
  --blueprint-sync \
  -vv
```
Blueprint status is exported so you can review the original course configuration, but enabling or managing blueprints in the target account still requires a manual step.

After a successful run the importer automatically rewrites page and assignment HTML so links to the source course (files, assignments, quizzes, discussions, modules, pages) are updated to the new target IDs using the generated `id_map.json`. No manual link cleanup is required as long as pages, assignments, files, quizzes, discussions, and modules are included in the import.

By default the importer also assigns the target course to the 'Default' enrollment term and sets participation to Course (restricts enrollments to course dates). Use `--term-name`, `--term-id`, `--no-auto-term`, or `--no-course-dates` when running `scripts/run_import.py` if you need different behaviour.

By default the importer clears SIS identifiers (sis_course_id, integration_id, sis_import_id). You can set new values with `--sis-course-id`, `--integration-id`, or `--sis-import-id` when running `scripts/run_import.py`.

Course hero images are remapped automatically when the original image file was exported and imported—the importer uses `id_map.json` to swap the old image file id for the new one before issuing the final course settings update.
 so links to the source course (files, assignments, quizzes, discussions, modules, pages) are updated to the new target IDs using the generated `id_map.json`. No manual link cleanup is required as long as pages, assignments, files, quizzes, discussions, and modules are included in the import.


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
