# tests/test_import_assignments.py
import json
from pathlib import Path

from tests.conftest import DummyCanvas
from importers import import_assignments as importer


def test_import_assignments_basic(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "wk1"
    a_dir.mkdir(parents=True)

    meta = {"id": 111, "name": "Week 1 Reflection", "published": True, "points_possible": 10}
    (a_dir / "assignment_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (a_dir / "description.html").write_text("<p>Say hello</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/222/assignments"
    requests_mock.post(create_url, json={"id": 999}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    counters = importer.import_assignments(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map["assignments"][111] == 999


def test_import_assignments_location_follow(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "wk2"
    a_dir.mkdir(parents=True)

    meta = {"id": 222, "name": "Week 2 Quiz", "published": False}
    (a_dir / "assignment_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (a_dir / "index.html").write_text("<p>Do things</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/333/assignments"
    follow_url = f"{api_base}/api/v1/courses/333/assignments/1234"

    requests_mock.post(create_url, json={}, status_code=201, headers={"Location": follow_url})
    requests_mock.get(follow_url, json={"id": 1234}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    counters = importer.import_assignments(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 1
    assert id_map["assignments"][222] == 1234


def test_assignment_payload_strips_unmapped_ids(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "wk3"
    a_dir.mkdir(parents=True)

    meta = {
        "id": 333,
        "name": "Group Project",
        "assignment_group_id": 444,
        "grading_standard_id": 555,
        "group_category_id": 666,
    }
    (a_dir / "assignment_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (a_dir / "index.html").write_text("<p>Group work</p>", encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/444/assignments"

    requests_mock.post(create_url, json={"id": 9999})

    canvas = DummyCanvas(api_base)
    id_map = {}

    importer.import_assignments(
        target_course_id=444,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    payload = requests_mock.last_request.json()["assignment"]
    assert "assignment_group_id" not in payload
    assert "grading_standard_id" not in payload
    assert "group_category_id" not in payload


def test_assignment_group_id_remaps_when_available(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "wk4"
    a_dir.mkdir(parents=True)

    meta = {
        "id": 444,
        "name": "Essay",
        "assignment_group_id": 11,
    }
    (a_dir / "assignment_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/555/assignments"
    requests_mock.post(create_url, json={"id": 7777})

    canvas = DummyCanvas(api_base)
    id_map = {"assignment_groups": {11: 99}}

    importer.import_assignments(
        target_course_id=555,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    payload = requests_mock.last_request.json()["assignment"]
    assert payload["assignment_group_id"] == 99

def test_assignment_online_quiz_skips(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    a_dir = export_root / "assignments" / "quiz-backed"
    a_dir.mkdir(parents=True)

    meta = {
        "id": 777,
        "name": "Module Quiz",
        "submission_types": ["online_quiz"],
    }
    (a_dir / "assignment_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.post(f"{api_base}/api/v1/courses/123/assignments", json={"id": 1})

    canvas = DummyCanvas(api_base)
    id_map = {}

    counters = importer.import_assignments(
        target_course_id=123,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["skipped"] == 1
    assert len(requests_mock.request_history) == 0
