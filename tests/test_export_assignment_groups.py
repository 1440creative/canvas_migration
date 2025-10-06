from __future__ import annotations

import json
from pathlib import Path

import requests_mock

from utils.api import CanvasAPI
from export.export_assignment_groups import export_assignment_groups


def test_export_assignment_groups_basic(tmp_path: Path) -> None:
    course_id = 321
    root = tmp_path / "export" / "data"
    api = CanvasAPI("https://canvas.test", "token")

    with requests_mock.Mocker() as m:
        m.get(
            f"https://canvas.test/api/v1/courses/{course_id}/assignment_groups",
            json=[
                {
                    "id": 11,
                    "name": "Homework",
                    "position": 1,
                    "group_weight": 40.0,
                    "assignments": [{"id": 55}, {"id": 44}],
                    "rules": [
                        {"rule": "drop_lowest", "value": 1},
                    ],
                }
            ],
        )

        metas = export_assignment_groups(course_id, root, api)

    groups_root = root / str(course_id) / "assignment_groups"
    meta_path = groups_root / "001_homework" / "assignment_group_metadata.json"
    assert meta_path.exists()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metas[0]["id"] == 11
    assert meta["name"] == "Homework"
    # assignment ids should be sorted deterministically
    assert meta["assignment_ids"] == [44, 55]
    assert meta["group_weight"] == 40.0
    assert meta["rules"] == [{"rule": "drop_lowest", "value": 1}]
