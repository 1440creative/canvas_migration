# tests/test_export_contract.py
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Toggle with: RUN_EXPORT_CONTRACT=1 pytest -q tests/test_export_contract.py
RUN = os.environ.get("RUN_EXPORT_CONTRACT") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="Set RUN_EXPORT_CONTRACT=1 to run exporter contract test")

class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - nothing to raise in fixtures
        return

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        return iter(())


class FakeSession:
    def __init__(self, api: "FakeCanvasAPI") -> None:
        self._api = api

    def get(self, url: str, timeout=None, stream: bool = False):
        payload = self._api._lookup(url)
        return FakeResponse(payload)


class FakeCanvasAPI:
    api_root = "https://canvas.test/api/v1/"

    def __init__(self, course_id: int):
        self.course_id = course_id
        self.session = FakeSession(self)
        self._responses = {
            #pages
            f"courses/{course_id}/pages": [
                {"page_id": 1, "id": 1, "url": "welcome", "title": "Welcome", "position": 1}
            ],
            f"courses/{course_id}/pages/welcome": {
                "page_id": 1, "url": "welcome", "title": "Welcome",
                "published": True, "updated_at": "2024-01-01T00:00:00Z",
                "body": "<h1>Welcome</h1>"
            },
            #assignments
            f"courses/{course_id}/assignments": [
                {
                    "id": 301,
                    "name": "Essay Draft",
                    "position": 1,
                    "published": True,
                    "updated_at": "2024-02-01T10:00:00Z",
                    "due_at": "2024-02-15T16:00:00Z",
                    "points_possible": 1,
                }
            ],
            f"courses/{course_id}/assignments/301": {
                "id": 301,
                "name": "Essay Draft",
                "description": "<p>Lorem ipsum dolor est.</p>",
                "published": True,
                "updated_at": "2024-02-01T10:00:00Z",
                "due_at": "2024-02-15T16:00:00Z",
                "points_possible": 1,
            },
            # quizzes
            f"courses/{course_id}/quizzes": [
                {
                    "id": 401,
                    "title": "Chapter 1 Quiz",
                    "position": 1,
                    "published": True,
                    "quiz_type": "graded_quiz",  # exporter normalizes this to "assignment"
                    "updated_at": "2024-03-01T08:00:00Z",
                }
            ],
            f"courses/{course_id}/quizzes/401": {
                "id": 401,
                "title": "Chapter 1 Quiz",
                "description": "<p>Answer all questions.</p>",
                "published": True,
                "quiz_type": "graded_quiz",
                "updated_at": "2024-03-01T08:00:00Z",
                "points_possible": 10,
                "time_limit": 30,
                "allowed_attempts": 1,
                "shuffle_answers": True,
                "one_question_at_a_time": False,
                "due_at": "2024-03-10T16:00:00Z",
            },
            f"courses/{course_id}/quizzes/401/questions": [
                {
                    "id": 9001,
                    "position": 1,
                    "question_name": "Question 1",
                    "question_text": "What is 2 + 2?",
                    "question_type": "multiple_choice_question",
                }
            ],
            #discussions
            f"courses/{course_id}/discussion_topics": [
                {
                    "id": 501,
                    "title": "Week 1 Check-in",
                    "position": 1,
                    "published": True,
                    "updated_at": "2024-04-01T09:00:00Z",
                }
            ],
            f"courses/{course_id}/discussion_topics/501": {
                "id": 501,
                "title": "Week 1 Check-in",
                "message": "<p>Say hello to the class.</p>",
                "published": True,
                "pinned": False,
                "locked": False,
                "require_initial_post": False,
                "discussion_type": "threaded",
                "posted_at": "2024-04-01T09:00:00Z",
                "last_reply_at": "2024-04-02T12:00:00Z",
                "updated_at": "2024-04-02T12:00:00Z",
            },
            #folders
            f"courses/{course_id}/folders": [
                {
                    "id": 7001,
                    "full_name": "course files",         # Canvas always includes this root
                },
                {
                    "id": 7002,
                    "full_name": "course files/Unit 1",  # becomes files/unit-1/
                },
            ],
            #files
            # Files list (one PDF in folder 7002 from your folders fixture)
            f"courses/{course_id}/files": [
                {
                    "id": 601,
                    "filename": "syllabus.pdf",
                    "display_name": "Syllabus.pdf",
                    "folder_id": 7002,                 # must match an id from courses/{cid}/folders
                    "size": 12345,
                    "content-type": "application/pdf", # exporter handles both hyphenated and underscored keys
                    "created_at": "2024-05-01T10:00:00Z",
                    "updated_at": "2024-05-01T10:00:00Z",
                    # omit url/download_url so the exporter takes the “no download” branch
                }
            ],
            # Detail fallback (exporter calls files/{fid} when no download_url)
            f"files/601": {
                # leave empty or repeat metadata; without a url the exporter still writes the sidecar
            },
            # modules
            f"courses/{course_id}/modules": [
                {
                    "id": 8001,
                    "name": "Week 1",
                    "position": 1,
                    "published": True,
                    "updated_at": "2024-06-01T09:00:00Z",
                }
            ],
            f"courses/{course_id}/modules/8001/items": [
                {
                    "id": 9001,
                    "position": 1,
                    "type": "Page",
                    "page_url": "welcome",
                    "title": "Welcome Page",
                    "html_url": f"https://canvas.test/courses/{course_id}/pages/welcome",
                },
                {
                    "id": 9002,
                    "position": 2,
                    "type": "Assignment",
                    "content_id": 301,
                    "title": "Essay Draft",
                    "html_url": f"https://canvas.test/courses/{course_id}/assignments/301",
                },
                {
                    "id": 9003,
                    "position": 3,
                    "type": "Quiz",
                    "content_id": 401,
                    "title": "Chapter 1 Quiz",
                    "html_url": f"https://canvas.test/courses/{course_id}/quizzes/401",
                },
                {
                    "id": 9004,
                    "position": 4,
                    "type": "File",
                    "content_id": 601,
                    "title": "Syllabus.pdf",
                    "html_url": f"https://canvas.test/courses/{course_id}/files/601",
                },
                {
                    "id": 9005,
                    "position": 5,
                    "type": "Discussion",
                    "content_id": 501,
                    "title": "Week 1 Check-in",
                    "html_url": f"https://canvas.test/courses/{course_id}/discussion_topics/501",
                },
            ],
            # course metadata
            f"courses/{course_id}": {
                "id": course_id,
                "uuid": "11111111-2222-3333-4444-555555555555",
                "sis_course_id": "SIS-COURSE-101",
                "name": "Migration Test Course",
                "course_code": "TEST101",
                "enrollment_term_id": 2024,
                "account_id": 200,
                "workflow_state": "available",
                "start_at": "2024-01-01T00:00:00Z",
                "end_at": "2024-06-01T00:00:00Z",
                "blueprint": False,
            },
            f"courses/{course_id}/settings": {
                "course_home_page": "modules",
                "allow_student_discussion_topics": True,
                "blueprint": False,
            },
            f"api/v1/courses/{course_id}": {
                "id": course_id,
                "syllabus_body": "<p>Overview</p>",
            },
        }

    def _normalize_key(self, endpoint: str) -> str:
        url = endpoint.split("?", 1)[0]
        if url.startswith(self.api_root):
            url = url[len(self.api_root):]
        return url.lstrip("/")

    def _lookup(self, endpoint: str):
        key = self._normalize_key(endpoint)
        data = self._responses.get(key)
        assert data is not None, f"FakeCanvasAPI missing fixture for {key}"
        return data

    def get(self, endpoint: str, params=None):
        return self._lookup(endpoint)



# --- Helpers ---------------------------------------------------------------

def _maybe_import(modname: str):
    try:
        return importlib.import_module(modname)
    except ModuleNotFoundError:
        return None

def _require(mod, fn: str):
    assert mod is not None, f"Missing module: {mod}"
    assert hasattr(mod, fn), f"Missing function: {mod.__name__}.{fn}"
    return getattr(mod, fn)

def _first(glob: str, root: Path) -> Path | None:
    matches = list(root.glob(glob))
    return matches[0] if matches else None

# --- Test ------------------------------------------------------------------

def test_export_contract_end_to_end(tmp_path: Path):
    """
    1) Calls your exporter entrypoints to write export/data/{SRC_ID}
    2) Asserts required files & minimal keys exist
    3) Runs the import runner in --dry-run and checks counts
    """
    SRC_ID = 101
    export_root = tmp_path / "export" / "data"
    course_root = export_root / str(SRC_ID)
    course_root.mkdir(parents=True, exist_ok=True)

    api = FakeCanvasAPI(SRC_ID)

    # ---- TODO-----------
    
    # If some exporters require API, you can pass a dummy/mocked client.
    mod_pages        = _maybe_import("export.export_pages")
    mod_assignments  = _maybe_import("export.export_assignments")
    mod_assignment_groups = _maybe_import("export.export_assignment_groups")
    mod_quizzes      = _maybe_import("export.export_quizzes")
    mod_discussions  = _maybe_import("export.export_discussions")
    mod_files        = _maybe_import("export.export_files")
    mod_modules      = _maybe_import("export.export_modules")
    mod_course       = _maybe_import("export.export_course")

    # Example function names (change as needed):
    #   export_pages(source_course_id: int, export_root: Path) -> None
    #   export_assignments(source_course_id: int, export_root: Path) -> None
    #   export_quizzes(source_course_id: int, export_root: Path, include_questions: bool = True) -> None
    #   export_discussions(source_course_id: int, export_root: Path) -> None
    #   export_files(source_course_id: int, export_root: Path) -> None
    #   export_modules(source_course_id: int, export_root: Path) -> None
    #   export_course(source_course_id: int, export_root: Path) -> None

    # Call what you have; comment out any you haven't implemented yet.
    if mod_pages:
        _require(mod_pages, "export_pages")(SRC_ID, export_root, api)
    if mod_assignments:
        _require(mod_assignments, "export_assignments")(SRC_ID, export_root, api)
    if mod_quizzes:
        _require(mod_quizzes, "export_quizzes")(SRC_ID, export_root, api, include_questions=True)
    if mod_discussions:
        _require(mod_discussions, "export_discussions")(SRC_ID, export_root, api)
    if mod_files:
        _require(mod_files, "export_files")(SRC_ID, export_root, api)
    if mod_modules:
        _require(mod_modules, "export_modules")(SRC_ID, export_root, api)
    if mod_assignment_groups:
        _require(mod_assignment_groups, "export_assignment_groups")(SRC_ID, export_root, api)
    if mod_course:
        _require(mod_course, "export_course")(SRC_ID, export_root, api)

    # ---- Contract checks: file layout --------------------------------------
    # Pages
    assert _first("pages/**/page_metadata.json", course_root), "page_metadata.json missing"
    assert _first("pages/**/index.html", course_root), "pages index.html missing"

    # Assignments
    assert _first("assignments/**/assignment_metadata.json", course_root), "assignment_metadata.json missing"
    # description.html is optional, but preferred
    # _first("assignments/**/description.html", out_root)

    # Assignment groups
    assert _first(
        "assignment_groups/**/assignment_group_metadata.json", course_root
    ), "assignment_group_metadata.json missing"

    # Quizzes
    assert _first("quizzes/**/quiz_metadata.json", course_root), "quiz_metadata.json missing"
    # optional bodies/questions:
    # _first("quizzes/**/description.html", out_root)
    # _first("quizzes/**/questions.json", out_root)

    # Discussions
    assert _first("discussions/**/discussion_metadata.json", course_root), "discussion_metadata.json missing"
    # _first("discussions/**/description.html", out_root)

    # Files (sidecar metadata next to file)
    assert _first("files/**/*.metadata.json", course_root), "*.metadata.json for files missing"

    # Modules
    modfile = course_root / "modules" / "modules.json"
    assert modfile.exists(), "modules/modules.json missing"

    # Course
    course_meta = course_root / "course" / "course_metadata.json"
    assert course_meta.exists(), "course/course_metadata.json missing"

    # ---- Minimal schema checks ---------------------------------------------
    # Page metadata keys
    pmeta = json.loads(_first("pages/**/page_metadata.json", course_root).read_text(encoding="utf-8"))
    for k in ["id", "title", "url", "published"]:
        assert k in pmeta, f"pages meta missing key: {k}"
    assert pmeta.get("html_path") in ["index.html", "body.html", pmeta.get("html_path")], "pages html_path should point to body file"

    # Assignment metadata keys
    ameta = json.loads(_first("assignments/**/assignment_metadata.json", course_root).read_text(encoding="utf-8"))
    for k in ["id", "name", "published"]:
        assert k in ameta, f"assignment meta missing key: {k}"

    # Assignment group metadata keys
    gmeta = json.loads(
        _first("assignment_groups/**/assignment_group_metadata.json", course_root).read_text(encoding="utf-8")
    )
    for k in ["id", "name", "assignment_ids"]:
        assert k in gmeta, f"assignment group meta missing key: {k}"

    # Quiz metadata keys
    qmeta = json.loads(_first("quizzes/**/quiz_metadata.json", course_root).read_text(encoding="utf-8"))
    for k in ["id", "title", "quiz_type", "published"]:
        assert k in qmeta, f"quiz meta missing key: {k}"

    # Discussion metadata keys
    dmeta = json.loads(_first("discussions/**/discussion_metadata.json", course_root).read_text(encoding="utf-8"))
    for k in ["id", "title"]:
        assert k in dmeta, f"discussion meta missing key: {k}"

    # Files sidecar keys
    fmeta = json.loads(_first("files/**/*.metadata.json", course_root).read_text(encoding="utf-8"))
    for k in ["id", "file_name"]:
        if k == "file_name":
            assert ("file_name" in fmeta) or ("filename" in fmeta), "file metadata sidecar missing key: file_name"
        else:
            assert k in fmeta, f"file metadata sidecar missing key: {k}"

    # Modules structure sanity
    mdata = json.loads(modfile.read_text(encoding="utf-8"))
    assert isinstance(mdata, list) and mdata, "modules.json should be a list with at least one module"
    first_items = mdata[0].get("items", [])
    assert isinstance(first_items, list), "module items must be a list"
    if first_items:
        t = first_items[0].get("type")
        assert t in {"SubHeader","Page","Assignment","Quiz","File","Discussion","ExternalUrl","ExternalTool"}, f"unexpected module item type: {t}"

    # Course minimal keys
    cmeta = json.loads(course_meta.read_text(encoding="utf-8"))
    for k in ["name", "course_code"]:
        assert k in cmeta, f"course_metadata missing key: {k}"

    # ---- Runner dry-run verification ---------------------------------------
    # Use repo’s runner to sanity-check counts (no API calls in dry-run)
    proj_root = Path.cwd()
    cmd = [
        sys.executable, "scripts/run_import.py",
        "--export-root", str(course_root),
        "--target-course-id", "999",
        "--dry-run", "-v",
    ]
    proc = subprocess.run(cmd, cwd=proj_root, capture_output=True, text=True)
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"dry-run failed:\n{combined}"
    for step in ["pages","assignments","quizzes","files","discussions","modules","course"]:
        assert f" - {step}" in combined, f"dry-run didn't report step: {step}"
