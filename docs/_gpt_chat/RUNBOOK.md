# Canvas Migration – Import Pipeline RUNBOOK
_Last updated: 2025-08-13_

This runbook is the minimal set of commands and steps to work on the **import pipeline**, with Modules up next.

---

## 0) Branch & Env

```bash
git checkout refactor/import-pipeline
git pull --rebase
python -V
pip install -r requirements.txt  # if needed
```
Environment:
- `.env` provides tokens/URLs. `utils/api.py` loads it automatically.
  - `CANVAS_SOURCE_URL` / `CANVAS_SOURCE_TOKEN`
  - `CANVAS_TARGET_URL` / `CANVAS_TARGET_TOKEN`

Quick sanity (Python REPL):
```python
from utils.api import target_api
target_api.api_root
```

---

## 1) Run All Tests

```bash
pytest -q
```

Focus on individual suites:
```bash
pytest -q tests/test_import_files.py
pytest -q tests/test_import_pages.py
pytest -q tests/test_import_assignments.py
pytest -q tests/test_import_quizzes.py
pytest -q tests/test_import_discussions.py
pytest -q tests/test_export_quizzes.py
# After you add modules test:
pytest -q tests/test_import_modules.py
```

---

## 2) What’s Implemented

- **Files** importer + test ✅
- **Pages** importer + test ✅
- **Assignments** importer + test ✅
- **Quizzes** importer (+ exporter normalized fields) + tests ✅
- **Discussions** importer (tests added; run & commit if not yet) 🟨
- **Modules** importer scaffold + test scaffold 🟨

Logging: use `get_logger(course_id=?, artifact=?)`. Set global verbosity in CLIs via `setup_logging()` (don’t pass `verbosity` into `get_logger`).

API wrapper: `CanvasAPI` supports `get/post/put/delete/post_json/begin_course_file_upload`.

---

## 3) ID Map (combined, in-memory)

```jsonc
{
  "files":        { "<old_id>": <new_id> },
  "pages":        { "<old_id>": <new_page_id?> },
  "pages_url":    { "<old_slug>": "<new_slug>" },
  "assignments":  { "<old_id>": <new_id> },
  "quizzes":      { "<old_id>": <new_id> },
  "discussions":  { "<old_id>": <new_id> },
  "modules":      { "<old_id>": <new_id> }
}
```

Persist recommendation:
```bash
# after a run, dump to file for debugging
python - <<'PY'
import json, pathlib
id_map = globals().get("id_map", {})  # or whichever scope
pathlib.Path("import_id_maps.json").write_text(json.dumps(id_map, indent=2, sort_keys=True))
print("wrote import_id_maps.json")
PY
```

---

## 4) Modules – Finish & Test

**Implement** `import/import_modules.py` (payloads per item type):  
- Create each module: `POST /courses/{{course_id}}/modules` with `name`, `position`, `published`, `unlock_at?`, `require_sequential_progress?`  
- Create items in deterministic order `(position, title, id)`

Item mappings:
- Page → `page_url = id_map["pages_url"][old_url]`
- Assignment → `content_id = id_map["assignments"][old_id]`
- Discussion → `content_id = id_map["discussions"][old_id]`
- Quiz → `content_id = id_map["quizzes"][old_id]`
- File → `content_id = id_map["files"][old_id]`
- ExternalUrl → `external_url`
- ExternalTool → `external_tool_url` (+ `new_tab?`)
- SubHeader → `title`

**Run tests** (after dropping in `tests/test_import_modules.py`):
```bash
pytest -q tests/test_import_modules.py
```

**Commit**:
```bash
git add import/import_modules.py tests/test_import_modules.py
git commit -m "feat(import): rebuild modules with ID mapping and tests"
git push
```

---

## 5) Optional: Quick Manual Drive (REPL)

```python
from pathlib import Path
from logging_setup import setup_logging
from utils.api import target_api
from importers.import_files import import_files
from importers.import_pages import import_pages
from importers.import_assignments import import_assignments
from importers.import_quizzes import import_quizzes
from importers.import_discussions import import_discussions
# from importers.import_modules import import_modules

setup_logging(2)
export_root = Path("export/data/SOURCE_COURSE_ID")  # adjust
id_map = {}

import_files(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map)
import_pages(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map)
import_assignments(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map)
import_quizzes(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map, include_questions=True)
import_discussions(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map)
# import_modules(target_course_id=NEW_COURSE_ID, export_root=export_root, canvas=target_api, id_map=id_map)
```

---

## 6) Link Rewriting (after Modules)

Implement a shared `import/link_rewriter.py`:
- Parse HTML bodies (pages, assignments, discussions, quizzes desc).  
- Replace intra-course links using `id_map`.  
- `PUT` updated content via the respective API endpoints.

---

## 7) Unified Runner (later)

Add `scripts/run_import_all.py` with flags:
```
--target-course --source-course --export-root --only-files --only-pages --only-assignments --only-quizzes --only-discussions --only-modules
```
- Construct `target_api` from `.env`
- Call steps in order; persist `import_id_maps.json`

---

## 8) Git Hygiene

```bash
git status
git add -A
git commit -m "feat(import): <what you did>"
git push
# open PR from refactor/import-pipeline → main
```

---

## 9) Gotchas

- `get_logger(...)` has no `verbosity` arg; set level via `setup_logging()` at entrypoints.
- File upload uses presigned URL — use plain `requests.post(upload_url, files=...)` then follow redirect with `canvas.session`.
- Pages in Modules require **slug** (`page_url`), not page id.
- `CanvasAPI.get()` adds `per_page=100`; tests should not rely on exact querystrings unless specified.
- Quizzes: API’s `graded_quiz` → metadata `quiz_type = "assignment"`.
