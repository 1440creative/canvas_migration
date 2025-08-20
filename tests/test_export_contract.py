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
    out_root = tmp_path / "export" / "data" / str(SRC_ID)
    out_root.mkdir(parents=True, exist_ok=True)

    # ---- TODO: wire these to your real exporter entrypoints ----------------
    # Adjust module paths & function names to your project.
    # If some exporters require API, you can pass a dummy/mocked client.
    mod_pages        = _maybe_import("exporters.export_pages")
    mod_assignments  = _maybe_import("exporters.export_assignments")
    mod_quizzes      = _maybe_import("exporters.export_quizzes")
    mod_discussions  = _maybe_import("exporters.export_discussions")
    mod_files        = _maybe_import("exporters.export_files")
    mod_modules      = _maybe_import("exporters.export_modules")
    mod_course       = _maybe_import("exporters.export_course")

    # Example function names (change as needed):
    #   export_pages(source_course_id: int, out_root: Path) -> None
    #   export_assignments(source_course_id: int, out_root: Path) -> None
    #   export_quizzes(source_course_id: int, out_root: Path, include_questions: bool = True) -> None
    #   export_discussions(source_course_id: int, out_root: Path) -> None
    #   export_files(source_course_id: int, out_root: Path) -> None
    #   export_modules(source_course_id: int, out_root: Path) -> None
    #   export_course(source_course_id: int, out_root: Path) -> None

    # Call what you have; comment out any you haven't implemented yet.
    if mod_pages:
        _require(mod_pages, "export_pages")(SRC_ID, out_root)
    if mod_assignments:
        _require(mod_assignments, "export_assignments")(SRC_ID, out_root)
    if mod_quizzes:
        _require(mod_quizzes, "export_quizzes")(SRC_ID, out_root, include_questions=True)
    if mod_discussions:
        _require(mod_discussions, "export_discussions")(SRC_ID, out_root)
    if mod_files:
        _require(mod_files, "export_files")(SRC_ID, out_root)
    if mod_modules:
        _require(mod_modules, "export_modules")(SRC_ID, out_root)
    if mod_course:
        _require(mod_course, "export_course")(SRC_ID, out_root)

    # ---- Contract checks: file layout --------------------------------------
    # Pages
    assert _first("pages/**/page_metadata.json", out_root), "page_metadata.json missing"
    assert _first("pages/**/index.html", out_root), "pages index.html missing"

    # Assignments
    assert _first("assignments/**/assignment_metadata.json", out_root), "assignment_metadata.json missing"
    # description.html is optional, but preferred
    # _first("assignments/**/description.html", out_root)

    # Quizzes
    assert _first("quizzes/**/quiz_metadata.json", out_root), "quiz_metadata.json missing"
    # optional bodies/questions:
    # _first("quizzes/**/description.html", out_root)
    # _first("quizzes/**/questions.json", out_root)

    # Discussions
    assert _first("discussions/**/discussion_metadata.json", out_root), "discussion_metadata.json missing"
    # _first("discussions/**/description.html", out_root)

    # Files (sidecar metadata next to file)
    assert _first("files/**/*.metadata.json", out_root), "*.metadata.json for files missing"

    # Modules
    modfile = out_root / "modules" / "modules.json"
    assert modfile.exists(), "modules/modules.json missing"

    # Course
    course_meta = out_root / "course" / "course_metadata.json"
    assert course_meta.exists(), "course/course_metadata.json missing"

    # ---- Minimal schema checks ---------------------------------------------
    # Page metadata keys
    pmeta = json.loads(_first("pages/**/page_metadata.json", out_root).read_text(encoding="utf-8"))
    for k in ["id", "title", "url", "published"]:
        assert k in pmeta, f"pages meta missing key: {k}"
    assert pmeta.get("html_path") in ["index.html", "body.html", pmeta.get("html_path")], "pages html_path should point to body file"

    # Assignment metadata keys
    ameta = json.loads(_first("assignments/**/assignment_metadata.json", out_root).read_text(encoding="utf-8"))
    for k in ["id", "name", "published"]:
        assert k in ameta, f"assignment meta missing key: {k}"

    # Quiz metadata keys
    qmeta = json.loads(_first("quizzes/**/quiz_metadata.json", out_root).read_text(encoding="utf-8"))
    for k in ["id", "title", "quiz_type", "published"]:
        assert k in qmeta, f"quiz meta missing key: {k}"

    # Discussion metadata keys
    dmeta = json.loads(_first("discussions/**/discussion_metadata.json", out_root).read_text(encoding="utf-8"))
    for k in ["id", "title"]:
        assert k in dmeta, f"discussion meta missing key: {k}"

    # Files sidecar keys
    fmeta = json.loads(_first("files/**/*.metadata.json", out_root).read_text(encoding="utf-8"))
    for k in ["id", "file_name"]:
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
        "--export-root", str(out_root),
        "--target-course-id", "999",
        "--dry-run", "-v",
    ]
    proc = subprocess.run(cmd, cwd=proj_root, capture_output=True, text=True)
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"dry-run failed:\n{combined}"
    for step in ["pages","assignments","quizzes","files","discussions","modules","course"]:
        assert f" - {step}" in combined, f"dry-run didn't report step: {step}"
