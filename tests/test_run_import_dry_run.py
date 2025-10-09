# tests/test_run_import_dry_run.py
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

def test_cli_dry_run_plan():
    project_root = Path.cwd()
    export_root = project_root / "sandbox_export" / "data" / "901"

    # Build a minimal export fixture with one item per step
    if export_root.exists():
        shutil.rmtree(export_root)

    def _write_json(path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    _write_json(export_root / "pages" / "page_metadata.json", {"id": 1, "title": "Sample Page"})
    _write_json(export_root / "assignment_groups" / "assignment_group_metadata.json", {"id": 10})
    _write_json(export_root / "assignments" / "assignment_metadata.json", {"id": 20})
    _write_json(export_root / "quizzes" / "quiz_metadata.json", {"id": 30})
    _write_json(export_root / "files" / "sample.txt.metadata.json", {"id": 40, "filename": "sample.txt"})
    _write_json(export_root / "discussions" / "discussion_metadata.json", {"id": 50})
    _write_json(export_root / "modules" / "modules.json", [{"id": 60}])
    _write_json(export_root / "course" / "course_metadata.json", {"id": 901, "name": "Sample Course"})

    # Ensure a .env exists so utils.api can instantiate clients at import-time
    env_path = project_root / ".env"
    env_path.write_text(
        "CANVAS_SOURCE_URL=https://source.example.edu\n"
        "CANVAS_SOURCE_TOKEN=token-source\n"
        "CANVAS_TARGET_URL=https://target.example.edu\n"
        "CANVAS_TARGET_TOKEN=token-target\n",
        encoding="utf-8"
    )

    cmd = [sys.executable, "scripts/run_import.py",
           "--export-root", str(export_root),
           "--target-course-id", "999",
           "--dry-run",
           "-v"]
    proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"Non-zero exit: {proc.returncode}\n{out}"

    # Expect the DRY-RUN plan and counts for each step
    assert "DRY-RUN: plan for steps" in out
    assert " - pages" in out and "1 item(s)" in out
    assert " - assignment_groups" in out and "1 item(s)" in out
    assert " - assignments" in out and "1 item(s)" in out
    assert " - quizzes" in out and "1 item(s)" in out
    assert " - files" in out and "1 item(s)" in out
    assert " - discussions" in out and "1 item(s)" in out
    assert " - modules" in out and "1 item(s)" in out
    assert " - course" in out and "1 item(s)" in out

    # id_map should be empty for dry-run
    assert "id_map keys present: none" in out
