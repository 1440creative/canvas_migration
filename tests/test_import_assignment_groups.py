import json
from pathlib import Path

from tests.conftest import DummyCanvas
from importers.import_assignment_groups import import_assignment_groups


def test_import_assignment_groups_creates_mapping(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    g_dir = export_root / "assignment_groups" / "001_homework"
    g_dir.mkdir(parents=True)

    meta = {
        "id": 11,
        "name": "Homework",
        "position": 1,
        "group_weight": 40.0,
        "rules": [{"rule": "drop_lowest", "value": 1}],
        "integration_data": {"foo": "bar"},
        "assignment_ids": [44, 55],
    }
    (g_dir / "assignment_group_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    api_base = "https://api.example.edu"
    create_url = f"{api_base}/api/v1/courses/999/assignment_groups"
    requests_mock.post(create_url, json={"id": 2222}, status_code=200)

    canvas = DummyCanvas(api_base)
    id_map = {}

    counters = import_assignment_groups(
        target_course_id=999,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
    )

    assert counters["imported"] == 1
    assert counters["failed"] == 0
    assert id_map["assignment_groups"][11] == 2222

    payload = requests_mock.last_request.json()
    assert payload["name"] == "Homework"
    assert payload["position"] == 1
    assert payload["group_weight"] == 40.0
    assert payload["rules"] == [{"rule": "drop_lowest", "value": 1}]
    assert payload["integration_data"] == {"foo": "bar"}
