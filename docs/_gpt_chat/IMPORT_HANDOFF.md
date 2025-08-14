# Canvas Migration: Import Pipeline Handoff (Modules Next)

_Last updated: 2025-08-13_

This document captures the current state of the **import pipeline** work, what’s already landed, and a crisp checklist to finish **Modules** and the remaining end-to-end wiring. It’s designed so you can resume quickly in a new session.

---

## Project Snapshot

- **Branch**: `refactor/import-pipeline`  
- **Status**: Files, Pages, Assignments, Quizzes, Discussions importers implemented (tests for most). Modules to finish/validate next.  
- **Export**: Deterministic structure in `export/data/{course_id}/` complete for pages, assignments, quizzes, files, discussions, modules (with `module_item_ids` backfill), course + blueprint settings.  
- **Logging**: Use `get_logger(course_id=?, artifact=?)`. Global verbosity controlled via `setup_logging()` in CLI entrypoints (do **not** pass `verbosity` into `get_logger`).  
- **API wrapper**: `utils/api.CanvasAPI` extended with `post`, `put`, `delete`, `post_json`, and `begin_course_file_upload()` (upload handshake). Session uses `Content-Type: application/json`.


## Implemented Importers (and where)

- `import/import_files.py`  
  - Uses `CanvasAPI.begin_course_file_upload()` → presigned `upload_url` → finalize redirect.  
  - Records `id_map["files"][old_id] = new_id`.
  - Unit test: `tests/test_import_files.py` ✅

- `import/import_pages.py`  
  - Reads `pages/**/page_metadata.json` and HTML body (`html_path` if present; fallbacks supported).  
  - POST `/courses/{course_id}/pages`, optional front page toggle.  
  - Records `id_map["pages"][old_id] = new_id` (when Canvas returns numeric id) and `id_map["pages_url"][old_slug] = new_slug`.  
  - Unit test: `tests/test_import_pages.py` ✅

- `import/import_assignments.py`  
  - Builds Canvas `{"assignment": {...}}` envelope with whitelisted fields; description from file if present.  
  - Records `id_map["assignments"][old_id] = new_id`.  
  - Unit test: `tests/test_import_assignments.py` ✅

- `import/import_quizzes.py`  
  - Builds Canvas `{"quiz": {...}}` envelope; description from file; optional questions import.  
  - Records `id_map["quizzes"][old_id] = new_id`.  
  - Unit test: `tests/test_import_quizzes.py` ✅  
  - **Exporter patch**: `export/export_quizzes.py` now normalizes `quiz_type` (`graded_quiz` → `assignment`) and writes expanded metadata (e.g., `points_possible`, `unlock_at`, `lock_at`, `scoring_policy`, `one_question_at_a_time`, `html_path`).  
  - **Test rewrite**: `tests/test_export_quizzes.py` uses `DummyAPI` for deterministic, fast tests ✅

- `import/import_discussions.py`  
  - Builds payload for `/courses/{course_id}/discussion_topics` with whitelisted fields; message/body from file.  
  - Records `id_map["discussions"][old_id] = new_id`.  
  - Unit test: `tests/test_import_discussions.py` (add and run) 🟨 (pending run/commit if not yet executed).


## Data Models (alignment)

`models.py` contains: `PageMeta`, `ModuleItemMeta`, `ModuleMeta`, `AssignmentMeta`, `FileMeta`, `CourseMeta`, `CourseStructure`.  
Added: **`QuizMeta`** (new) with keys we now export and import:
- `id`, `title`, `quiz_type`, `published`, `points_possible`, `time_limit`, `allowed_attempts`, `shuffle_answers`, `scoring_policy`, `one_question_at_a_time`, `due_at`, `unlock_at`, `lock_at`, `html_path`, `updated_at`, `module_item_ids`, `source_api_url`.

> Importers prefer `html_path` from metadata; fallback file names remain in place (e.g., `index.html`, `description.html`, `body.html`).


## ID Map Schema (combined)

During import, we build a single in-memory map (persist later to JSON if desired):

```jsonc
{
  "files":        { "<old_id:int>": <new_id:int>, ... },
  "pages":        { "<old_id:int>": <new_id:int> },           // when Canvas returns numeric page_id
  "pages_url":    { "<old_slug:str>": "<new_slug:str>" },      // always used for Module Page items
  "assignments":  { "<old_id:int>": <new_id:int> },
  "quizzes":      { "<old_id:int>": <new_id:int> },
  "discussions":  { "<old_id:int>": <new_id:int> },
  "modules":      { "<old_id:int>": <new_id:int> }             // filled by modules importer
}
```

These maps drive **intra-course link rewriting** and **Modules** rebuild.


## Export Layout (assumptions the importers use)

```
export/
└─ data/
   └─ {source_course_id}/
      ├─ files/**/<file> + <file>.metadata.json
      ├─ pages/**/page_metadata.json + index.html (or html_path)
      ├─ assignments/**/assignment_metadata.json + description.html (or html_path)
      ├─ quizzes/**/quiz_metadata.json + description.html (or html_path) + questions.json?
      ├─ discussions/**/discussion_metadata.json + index.html (or html_path)
      └─ modules/modules.json  (list of ModuleMeta-like dicts with items)
```


## Modules: Implementation Plan (finish tomorrow)

**File**: `import/import_modules.py` (scaffold provided)  
**Goal**: Create modules in order and add items, mapping content via `id_map`.

### 1) Create Modules
- Payload: `{"module": {"name", "position", "published", "require_sequential_progress", "unlock_at?"}}`
- Endpoint: `POST /api/v1/courses/{course_id}/modules`
- Record `id_map["modules"][old_module_id] = new_module_id`

### 2) Create Module Items (deterministic order)
- Sort: `(position, title, id)` to guarantee stability.
- Endpoint: `POST /api/v1/courses/{course_id}/modules/{module_id}/items`
- Payloads by type:
  - **Page** → `{"module_item": {"type": "Page", "page_url": <new_slug>}}`
      - Map via `id_map["pages_url"][old_url]`
  - **Assignment** → `{"content_id": <id_map["assignments"][old_id]>}`
  - **Discussion** → `{"content_id": <id_map["discussions"][old_id]>}`
  - **Quiz** → `{"content_id": <id_map["quizzes"][old_id]>}`
  - **File** → `{"content_id": <id_map["files"][old_id]>}`
  - **ExternalUrl** → `{"external_url": <url>, "title": <title>}`
  - **ExternalTool** → `{"external_tool_url": <url>, "new_tab": <bool?>}`
  - **SubHeader** → `{"title": <title>}`
- If a necessary mapping is missing, **log and skip** that item (don’t fail the whole module).

### 3) Fine Points / Future Enhancements
- Preserve `indent` and `position` if present in item metadata.
- Optional: support `completion_requirement` (requires separate `PUT` per item).
- Optional: support prerequisites (module-to-module associations).

### 4) Unit Tests
- `tests/test_import_modules.py` scaffold provided to validate:
  - Correct POST to create module.
  - Correct POSTs per item type (including Page `page_url` mapping).
  - Uses `id_map` correctly and in order.

### 5) Integration Check (after all importers)
- Run a sandbox import: Files → Pages → Assignments → Quizzes → Discussions → Modules.  
- Verify modules display correctly; links and attachments open.


## HTML Link Rewriting (next after modules)

Implement a shared utility (e.g., `import/link_rewriter.py`) that:
- Scans HTML (`pages`, `assignments`, `discussions`, and quiz descriptions).
- Rewrites `href/src` matching intra-course patterns to their new targets using `id_map` + known URL shapes.  
- Special-case files: `/files/<old_id>/download` → `/files/<new_id>/download` or new hosted URL variant.

Run it **after** content creation (once you have new IDs), then `PUT` the updated body back to Canvas.


## Unified Runner (optional next step)

Create `scripts/run_import_all.py` with flags:
```
--target-course <id> --source-course <id> --export-root <path> --api-base <url> [--only-files --only-pages --only-assignments --only-quizzes --only-discussions --only-modules]
```
- Construct `CanvasAPI` (target) from env (`CANVAS_TARGET_URL`, `CANVAS_TARGET_TOKEN`).  
- Call steps in order, accumulating `id_map`.  
- Persist `id_map` to `import_id_maps.json` for debugging and link rewriting.


## Quick Commands (tomorrow)

```bash
# Ensure you’re on the correct branch
git checkout refactor/import-pipeline
git pull --rebase

# Run all tests
pytest -q

# Just discussions tests
pytest -q tests/test_import_discussions.py

# Just modules tests (after you add/commit them)
pytest -q tests/test_import_modules.py
```


## Open Loops / TODO Checklist

- [ ] **Discussions**: run tests, commit if not yet.  
- [ ] **Modules**: finish/import (use provided scaffold), add tests, commit.  
- [ ] **Link rewriting**: implement HTML rewriter + update bodies via `PUT`.  
- [ ] **Runner**: `run_import_all.py` with `--only-*` switches and persisted `id_map`.  
- [ ] **Blueprint**: apply blueprint associations/settings post-import (if applicable).  
- [ ] **Integration**: sandbox round-trip (Export → Import → Smoke test in Canvas).


---

### Notes on Environment & Auth
- Set tokens in `.env`; `utils/api.py` uses `dotenv` to instantiate `source_api` / `target_api`.  
- For one-off runs, you can also pass a `CanvasAPI` constructed with `CANVAS_TARGET_URL` + `CANVAS_TARGET_TOKEN`.

Good luck picking it up tomorrow—Modules should be a quick win with the scaffold and tests already laid out.
