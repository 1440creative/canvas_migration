# tests/test_run_import_dry_run.py
import os, sys, subprocess, json
from pathlib import Path

def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def _mk_sandbox(root: Path):
    """
    Create a minimal export tree with 1 item per artifact so the CLI --dry-run
    prints '1 item(s)' for each step.
    """
    # pages
    _write(root / "pages" / "001_welcome" / "page_metadata.json",
           json.dumps({"id": 1, "url": "welcome", "title": "Welcome", "published": True}))
    _write(root / "pages" / "001_welcome" / "index.html", "<h1>Welcome</h1>")

    # assignments
    _write(root / "assignments" / "001_hw-1" / "assignment_metadata.json",
           json.dumps({"id": 2, "name": "HW 1", "published": True}))
    _write(root / "assignments" / "001_hw-1" / "index.html", "<p>Do HW 1</p>")

    # quizzes
    _write(root / "quizzes" / "001_quiz-1" / "quiz_metadata.json",
           json.dumps({"id": 3, "title": "Quiz 1", "quiz_type": "assignment", "published": True}))
    _write(root / "quizzes" / "001_quiz-1" / "index.html", "<p>Quiz body</p>")

    # files (sidecar next to the real file)
    file_path = root / "files" / "docs" / "readme.txt"
    _write(file_path, "hello")
    _write(file_path.with_name(file_path.name + ".metadata.json"),
           json.dumps({"id": 4, "filename": "readme.txt", "folder_path": "docs", "file_path": "files/docs/readme.txt",
                       "module_item_ids": []}))

    # discussions
    _write(root / "discussions" / "001_welcome-thread" / "discussion_metadata.json",
           json.dumps({"id": 5, "title": "Welcome thread", "published": True}))
    _write(root / "discussions" / "001_welcome-thread" / "index.html", "<p>Discuss</p>")

    # modules
    _write(root / "modules" / "001_7" / "module_metadata.json",
           json.dumps({"id": 7, "name": "Week 1", "position": 1, "published": True, "items": []}))

    # course
    _write(root / "course" / "course_metadata.json",
           json.dumps({"id": 901, "name": "Sandbox", "is_blueprint": False}))
    _write(root / "course" / "course_settings.json", json.dumps({"default_view": "modules"}))

def test_cli_dry_run_plan():
    project_root = Path.cwd()
    export_root = project_root / "sandbox_export" / "data" / "901"

    # Ensure a .env exists so utils.api can instantiate clients at import-time
    env_path = project_root / ".env"
    env_path.write_text(
        "CANVAS_SOURCE_URL=https://source.example.edu\n"
        "CANVAS_SOURCE_TOKEN=token-source\n"
        "CANVAS_TARGET_URL=https://target.example.edu\n"
        "CANVAS_TARGET_TOKEN=token-target\n",
        encoding="utf-8"
    )

    # Create the mini-export tree the CLI will scan
    _mk_sandbox(export_root)

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
    assert " - assignments" in out and "1 item(s)" in out
    assert " - quizzes" in out and "1 item(s)" in out
    assert " - files" in out and "1 item(s)" in out
    assert " - discussions" in out and "1 item(s)" in out
    assert " - modules" in out and "1 item(s)" in out
    assert " - course" in out and "1 item(s)" in out

    # id_map should be empty for dry-run
    assert "id_map keys present: none" in out
