# tests/test_import_discussions.py
import json
import os
from pathlib import Path

from tests.conftest import DummyCanvas, load_importer


def test_import_discussions_basic(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    disc_dir = export_root / "discussions" / "welcome-thread"
    disc_dir.mkdir(parents=True)

    meta = {
        "id": 987,
        "title": "Welcome thread",
        # explicitly NOT an announcement
        "is_announcement": False,
        "published": True,
        "html_path": "index.html",
        "assignment_id": None,
    }
    (disc_dir / "discussion_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (disc_dir / "index.html").write_text("<p>Hello class 👋</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/discussion_topics"

    # POST create returns id directly
    requests_mock.post(
        create_url,
        json={"id": 123, "title": "Welcome thread"},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    project_root = Path(os.getcwd())
    importer = load_importer(project_root, module="importers.import_discussions")

    id_map = {}

    # --- Act
    counters = importer.import_discussions(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 0
    # id map recorded
    assert id_map.get("discussions", {}).get(987) == 123


def test_import_discussions_location_follow(tmp_path, requests_mock):
    # --- Arrange export tree
    export_root = tmp_path / "export" / "data" / "101"
    disc_dir = export_root / "discussions" / "syllabus-qna"
    disc_dir.mkdir(parents=True)

    meta = {
        "id": 321,
        "title": "Syllabus Q&A",
        "is_announcement": False,
        "published": False,
        # no html_path => defaults to index.html
        "assignment_id": None,
    }
    (disc_dir / "discussion_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (disc_dir / "index.html").write_text("<p>Ask anything about the syllabus.</p>", encoding="utf-8")

    # --- Arrange API mocks
    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/discussion_topics"
    follow_url = f"{api_base}/api/v1/courses/222/discussion_topics/654"

    # POST returns no id in JSON but gives Location to follow
    requests_mock.post(
        create_url,
        json={"result": "ok"},
        status_code=201,
        headers={"Location": follow_url},
    )
    # GET follow returns full topic with id
    requests_mock.get(
        follow_url,
        json={"id": 654, "title": "Syllabus Q&A"},
        status_code=200,
    )

    canvas = DummyCanvas(api_base)
    project_root = Path(os.getcwd())
    importer = load_importer(project_root, module="importers.import_discussions")

    id_map = {}

    # --- Act
    counters = importer.import_discussions(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    # --- Assert
    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map.get("discussions", {}).get(321) == 654


def test_import_discussions_skips_assignment_backed(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    disc_dir = export_root / "discussions" / "graded-topic"
    disc_dir.mkdir(parents=True)

    meta = {
        "id": 555,
        "title": "Graded Topic",
        "is_announcement": False,
        "published": True,
        "html_path": "index.html",
        "assignment_id": 999,
    }
    (disc_dir / "discussion_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (disc_dir / "index.html").write_text("<p>Discuss for points</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/discussion_topics"

    requests_mock.post(create_url, json={"id": 777}, status_code=200)

    canvas = DummyCanvas(api_base)
    project_root = Path(os.getcwd())
    importer = load_importer(project_root, module="importers.import_discussions")

    id_map = {}

    counters = importer.import_discussions(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 0
    assert counters["skipped"] == 1
    assert counters["failed"] == 0
    assert "discussions" not in id_map or 555 not in id_map["discussions"]
