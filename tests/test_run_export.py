# tests/test_run_export.py
from __future__ import annotations
import sys
import types
import builtins
from pathlib import Path
import pytest

import scripts.run_export as runner


def test_run_export_runs_steps(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    # fake export functions
    def fake_export(course_id, root, api, **kwargs):
        calls.append(kwargs.get("name", "x"))
        return [{"id": 1}]

    # monkeypatch each export_* to fake
    monkeypatch.setattr(runner, "export_pages", lambda cid, root, api: [{"id": 1}])
    monkeypatch.setattr(runner, "export_assignments", lambda cid, root, api: [{"id": 2}])
    monkeypatch.setattr(runner, "export_quizzes", lambda cid, root, api, **kw: [{"id": 3}])
    monkeypatch.setattr(runner, "export_files", lambda cid, root, api: [{"id": 4}])
    monkeypatch.setattr(runner, "export_discussions", lambda cid, root, api: [{"id": 5}])
    monkeypatch.setattr(runner, "export_announcements", lambda cid, root, api: [{"id": 6}])
    monkeypatch.setattr(runner, "export_modules", lambda cid, root, api: [{"id": 7}])
    monkeypatch.setattr(runner, "export_course_settings", lambda cid, root, api: {"id": 8})
    monkeypatch.setattr(runner, "export_blueprint_settings", lambda cid, root, api: {"bp": False})

    testargs = ["prog", "--course-id", "101", "--export-root", str(tmp_path), "--steps", "pages", "announcements"]
    monkeypatch.setattr(sys, "argv", testargs)

    exitcode = runner.main()
    assert exitcode == 0
