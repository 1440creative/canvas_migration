# tests/test_rubrics.py
from __future__ import annotations
import json
from pathlib import Path

from utils.api import CanvasAPI
from export.export_rubrics import export_rubrics
from importers.import_rubrics import import_rubrics


def test_export_rubrics_writes_slim_json(tmp_path, requests_mock):
    course_id = 101
    base_host = "https://canvas.test"

    # Mock GET /rubrics with associations included
    requests_mock.get(
        f"{base_host}/api/v1/courses/{course_id}/rubrics",
        json=[{
            "id": 55,
            "title": "Project Rubric",
            "points_possible": 30,
            "free_form_criterion_comments": False,
            "criteria": [
                {
                    "id": "crit_1",
                    "description": "Clarity",
                    "long_description": "Writing is clear",
                    "points": 10,
                    "ignore_for_scoring": False,
                    "ratings": [
                        {"id": "r1", "description": "Excellent", "points": 10},
                        {"id": "r2", "description": "OK", "points": 6},
                        {"id": "r3", "description": "Poor", "points": 2},
                    ],
                }
            ],
            "associations": [
                {
                    "association_type": "Assignment",
                    "association_id": 2001,
                    "use_for_grading": True,
                    "purpose": "grading",
                    "hide_score_total": False,
                    "hide_points": False,
                }
            ],
        }],
    )

    api = CanvasAPI(base_host, "tkn")
    out = export_rubrics(course_id, tmp_path, api)

    # Check return value and file on disk
    assert isinstance(out, list) and len(out) == 1
    out_file = tmp_path / "rubrics" / "rubrics.json"
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data[0]["title"] == "Project Rubric"
    assert isinstance(data[0]["criteria"], list) and data[0]["criteria"][0]["description"] == "Clarity"
    # Slim shape (no unexpected top-level keys)
    assert set(data[0].keys()) >= {"id", "title", "criteria", "associations", "points_possible"}


def test_import_rubrics_creates_and_associates(tmp_path, requests_mock):
    target_course_id = 2457
    base_host = "https://canvas.test"

    # Prepare exported rubrics.json
    rubrics_dir = tmp_path / "rubrics"
    rubrics_dir.mkdir(parents=True, exist_ok=True)
    exported = [{
        "id": 55,
        "title": "Project Rubric",
        "free_form_criterion_comments": False,
        "criteria": [
            {
                "description": "Clarity",
                "long_description": "Writing is clear",
                "points": 10,
                "ignore_for_scoring": False,
                "ratings": [
                    {"description": "Excellent", "points": 10},
                    {"description": "OK", "points": 6},
                    {"description": "Poor", "points": 2},
                ],
            }
        ],
        "associations": [
            {
                "association_type": "Assignment",
                "association_id": 2001,  # old assignment id from source
                "use_for_grading": True,
                "purpose": "grading",
                "hide_score_total": False,
                "hide_points": False,
            }
        ],
    }]
    (rubrics_dir / "rubrics.json").write_text(json.dumps(exported), encoding="utf-8")

    # id_map with assignment mapping (source 2001 -> target 9001)
    id_map = {"assignments": {2001: 9001}}

    # Mock rubric creation -> returns new rubric id
    def _match_create_rubric(request):
        body = request.json()
        assert body["rubric"]["title"] == "Project Rubric"
        assert body["rubric"]["criteria"][0]["description"] == "Clarity"
        return True

    requests_mock.post(
        f"{base_host}/api/v1/courses/{target_course_id}/rubrics",
        additional_matcher=_match_create_rubric,
        json={"id": 7001, "title": "Project Rubric"},
        status_code=201,
    )

    # Mock association post
    created_assocs = []
    def _match_assoc(request):
        payload = request.json()
        ra = payload["rubric_association"]
        created_assocs.append(ra)
        # Expect association_id to be the mapped assignment id and rubric_id = 7001
        assert ra["association_type"] == "Assignment"
        assert ra["association_id"] == 9001
        assert ra["rubric_id"] == 7001
        return True

    requests_mock.post(
        f"{base_host}/api/v1/courses/{target_course_id}/rubric_associations",
        additional_matcher=_match_assoc,
        json={"id": 888},
        status_code=201,
    )

    api = CanvasAPI(base_host, "tkn")
    from importers.import_rubrics import import_rubrics as do_import
    do_import(target_course_id=target_course_id, export_root=tmp_path, canvas=api, id_map=id_map)

    # id_map updated with rubric mapping
    assert id_map.get("rubrics", {}).get(55) == 7001
    # 1 association created and matched new assignment id
    assert len(created_assocs) == 1
