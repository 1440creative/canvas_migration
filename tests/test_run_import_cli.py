from __future__ import annotations

import pytest

from scripts.run_import import main


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeCanvasAPI:
    def __init__(self, base, token):
        self.base = base
        self.token = token
        root = base.rstrip("/")
        self.base_url = f"{root}/"
        self.api_root = f"{root}/api/v1/"
        self.session = object()
        self.created_courses: list[dict] = []

    def post(self, endpoint, json=None, **kwargs):
        self.created_courses.append({"endpoint": endpoint, "json": json})
        return _FakeResponse({"id": 555})


def test_dry_run_without_target_id(tmp_path, capsys):
    export_root = tmp_path / "export" / "data" / "101"
    export_root.mkdir(parents=True, exist_ok=True)

    rc = main(["--export-root", str(export_root), "--dry-run"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out


def test_real_run_requires_target_id(tmp_path):
    export_root = tmp_path / "export" / "data" / "101"
    export_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as excinfo:
        main(["--export-root", str(export_root)])

    assert excinfo.value.code == 2


def test_missing_target_id_creates_course(tmp_path, monkeypatch, capsys):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / "course_metadata.json").write_text('{"name": "Imported Course"}', encoding="utf-8")

    created: dict[str, int] = {}

    def fake_import_course(*, target_course_id, **kwargs):  # type: ignore[no-untyped-def]
        created["target_id"] = target_course_id
        created["include_quiz_questions"] = kwargs.get("include_quiz_questions")
        return {"counts": {}, "errors": []}

    monkeypatch.setattr("scripts.run_import.import_course", fake_import_course)
    monkeypatch.setattr("utils.api.CanvasAPI", _FakeCanvasAPI)
    monkeypatch.setenv("CANVAS_TARGET_URL", "https://canvas.test")
    monkeypatch.setenv("CANVAS_TARGET_TOKEN", "token")

    rc = main([
        "--export-root",
        str(export_root),
        "--target-account-id",
        "135",
    ])

    assert rc == 0
    assert created.get("target_id") == 555
    assert created.get("include_quiz_questions") is True
    output = capsys.readouterr().out
    assert "Created new Canvas course 555" in output


def test_skip_quiz_questions_flag(tmp_path, monkeypatch):
    export_root = tmp_path / "export" / "data" / "101"
    export_root.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def fake_import_course(*, target_course_id, **kwargs):  # type: ignore[no-untyped-def]
        captured["include_quiz_questions"] = kwargs.get("include_quiz_questions")
        return {"counts": {}, "errors": []}

    monkeypatch.setattr("scripts.run_import.import_course", fake_import_course)
    monkeypatch.setattr("utils.api.CanvasAPI", _FakeCanvasAPI)
    monkeypatch.setenv("CANVAS_TARGET_URL", "https://canvas.test")
    monkeypatch.setenv("CANVAS_TARGET_TOKEN", "token")

    rc = main([
        "--export-root",
        str(export_root),
        "--target-course-id",
        "321",
        "--skip-quiz-questions",
    ])

    assert rc == 0
    assert captured.get("include_quiz_questions") is False
