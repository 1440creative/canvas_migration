# tests/test_import_course_settings.py
import json
import logging
import re
from pathlib import Path

from importers.import_course_settings import import_course_settings
from tests.conftest import DummyCanvas


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_puts_course_fields_and_settings(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Physics 101",
        "course_code": "PHYS101",
        "settings": {"hide_distribution_graphs": True},
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Two PUTs: /courses/:id and /courses/:id/settings
    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/222/settings", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert counts["updated"] >= 2
    assert put_course.called
    assert put_settings.called
    body = put_course.last_request.json()
    assert "account_id" not in body.get("course", {})
    assert body["course"]["sis_course_id"] == ""
    assert body["course"]["integration_id"] == ""
    assert body["course"]["sis_import_id"] == ""


def test_puts_syllabus_html(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    _write(course_dir / "syllabus.html", "<h1>Syllabus</h1>")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Syllabus is PUT to /courses/:id
    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert counts["updated"] >= 1
    assert put_course.called


def test_sets_default_view_and_front_page(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    _write(
        course_dir / "home.json",
        json.dumps({"default_view": "modules", "front_page_url": "front"}),
    )

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_default_view = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )
    put_front_page = requests_mock.put(
        f"{api_base}/api/v1/courses/222/pages/front", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    # Expect two updates (default_view + front_page)
    assert counts["updated"] >= 2
    assert put_default_view.called
    assert put_front_page.called


def test_sets_apply_assignment_group_weights(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True)

    meta = {
        "name": "Weighted Course",
        "course_code": "WC",
        "apply_assignment_group_weights": True,
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/222"
    requests_mock.put(course_url, json={"ok": True}, status_code=200)
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    payload = requests_mock.request_history[0].json()["course"]
    assert payload["apply_assignment_group_weights"] is True


def test_infers_assignment_group_weights(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True)

    # course metadata without explicit flag
    meta = {
        "name": "Weighted Course",
        "course_code": "WC",
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    groups_dir = export_root / "assignment_groups" / "001_group"
    groups_dir.mkdir(parents=True)
    gmeta = {
        "id": 1,
        "name": "Group",
        "group_weight": 25,
        "assignment_ids": [],
    }
    (groups_dir / "assignment_group_metadata.json").write_text(json.dumps(gmeta), encoding="utf-8")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/222"
    requests_mock.put(course_url, json={"ok": True}, status_code=200)
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    payload = requests_mock.request_history[0].json()["course"]
    assert payload["apply_assignment_group_weights"] is True


def test_reapplies_assignment_group_weights(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True)

    meta = {"name": "Weighted Course", "course_code": "WC"}
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    groups_dir = export_root / "assignment_groups" / "001_group"
    groups_dir.mkdir(parents=True)
    gmeta = {
        "id": 11,
        "name": "Engagement Assessments",
        "group_weight": 35.0,
        "assignment_ids": [],
    }
    (groups_dir / "assignment_group_metadata.json").write_text(json.dumps(gmeta), encoding="utf-8")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/333"
    requests_mock.put(course_url, json={"ok": True}, status_code=200)
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    group_put_url = f"{api_base}/api/v1/courses/333/assignment_groups/99"
    group_matcher = requests_mock.put(group_put_url, json={"id": 99}, status_code=200)

    id_map = {"assignment_groups": {11: 99}}

    import_course_settings(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
        id_map=id_map,
    )

    assert group_matcher.called
    payload = group_matcher.last_request.json()["assignment_group"]
    assert payload["group_weight"] == 35.0


def test_reapplies_assignment_group_weights_logs_http_error(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True)

    meta = {"name": "Weighted Course", "course_code": "WC"}
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    groups_dir = export_root / "assignment_groups" / "001_group"
    groups_dir.mkdir(parents=True)
    gmeta = {
        "id": 11,
        "name": "Engagement Assessments",
        "group_weight": 20.0,
        "assignment_ids": [],
    }
    (groups_dir / "assignment_group_metadata.json").write_text(json.dumps(gmeta), encoding="utf-8")

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/333"
    requests_mock.put(course_url, json={"ok": True}, status_code=200)
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    group_put_url = f"{api_base}/api/v1/courses/333/assignment_groups/99"
    group_matcher = requests_mock.put(group_put_url, json={"error": "nope"}, status_code=400)

    id_map = {"assignment_groups": {11: 99}}

    with caplog.at_level(logging.WARNING, logger="canvas_migrations"):
        import_course_settings(
            target_course_id=333,
            export_root=export_root,
            canvas=canvas,
            auto_set_term=False,
            participation_mode="inherit",
            id_map=id_map,
        )

    assert group_matcher.called
    assert "Failed to reapply group weight" in caplog.text


def test_blueprint_sync_optional(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )
    post_bp = requests_mock.post(
        f"{api_base}/api/v1/courses/222/blueprint_templates/default/migrations",
        json={"migration_id": 1},
        status_code=200,
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
        queue_blueprint_sync=True,
        blueprint_sync_options={"copy_settings": True, "publish_after_migration": True},
    )

    # This call doesn't bump "updated" (we only count PUTs), but should hit the POST.
    assert isinstance(counts, dict)
    assert post_bp.called


def test_target_account_id_overrides_course_lookup(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    _write(course_dir / "course_metadata.json", json.dumps({"name": "Chemistry"}))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222", json={"ok": True}, status_code=200
    )

    get_course = requests_mock.get(
        f"{api_base}/api/v1/courses/222",
        json={"id": 222, "account_id": 99},
        status_code=200,
    )

    get_terms = requests_mock.get(
        f"{api_base}/api/v1/accounts/54/terms",
        json={"enrollment_terms": [{"id": 321, "name": "Default Term"}]},
        status_code=200,
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        target_account_id=54,
        term_name="Default Term",
        participation_mode="inherit",
    )

    assert counts["updated"] >= 1
    assert not get_course.called  # override skips course metadata fetch
    assert get_terms.called
    body = put_course.last_request.json()
    assert body["course"]["enrollment_term_id"] == 321


def test_maps_course_image_with_id_map(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Design 200",
        "image_id": 111,
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/333", json={"ok": True}, status_code=200
    )

    counts = import_course_settings(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map={"files": {111: 999}},
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert counts["updated"] >= 1
    assert put_course.called
    body = put_course.last_request.json()
    assert body["course"]["image_id"] == 999
    assert body["course"]["image_url"] is None


def test_course_image_falls_back_to_settings_image_id(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Design 201",
        "settings": {
            "image": "https://canvas.test/courses/101/files/123/download",
            "image_id": "123",
        },
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/334", json={"ok": True}, status_code=200
    )

    requests_mock.put(
        f"{api_base}/api/v1/courses/334/settings", json={"ok": True}, status_code=200
    )

    import_course_settings(
        target_course_id=334,
        export_root=export_root,
        canvas=canvas,
        id_map={"files": {123: 444}},
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert put_course.called
    body = put_course.last_request.json()
    course_payload = body["course"]
    assert course_payload["image_id"] == 444
    assert course_payload["image_url"] is None


def test_auto_term_and_course_participation(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {"name": "History", "account_id": 42}
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    # Mock course lookup and term lookup
    requests_mock.get(
        f"{api_base}/api/v1/courses/444",
        json={"id": 444, "account_id": 42},
        status_code=200,
    )
    requests_mock.get(
        f"{api_base}/api/v1/accounts/42/terms",
        json={"enrollment_terms": [{"id": 314, "name": "Default Term"}]},
        status_code=200,
    )

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/444", json={"ok": True}, status_code=200
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/444/settings", json={"ok": True}, status_code=200
    )

    import_course_settings(
        target_course_id=444,
        export_root=export_root,
        canvas=canvas,
        id_map={},
    )

    body = put_course.last_request.json()
    course_payload = body["course"]
    assert course_payload["enrollment_term_id"] == 314
    assert course_payload["restrict_enrollments_to_course_dates"] is True
    settings_payload = put_settings.last_request.json()
    assert settings_payload["restrict_enrollments_to_course_dates"] is True


def test_grading_standard_failure_falls_back_to_course_dates(tmp_path, requests_mock, caplog):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "History",
        "account_id": 135,
        "grading_standard_enabled": True,
        "grading_standard_id": 5017,
        "settings": {
            "grading_standard_enabled": True,
            "grading_standard_id": 5017,
        },
        "start_at": "2025-01-08T00:00:00Z",
        "end_at": "2025-04-30T23:59:00Z",
    }
    meta["grading_standard"] = {
        "title": "Non-Credit Standard (rounding-enabled)",
        "grading_scheme": [
            {"name": "Pass", "value": 0.7},
            {"name": "Fail", "value": 0.0},
        ],
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_id = 555

    requests_mock.get(
        f"{api_base}/api/v1/courses/{course_id}",
        json={"id": course_id, "account_id": 135},
        status_code=200,
    )
    requests_mock.get(
        f"{api_base}/api/v1/accounts/135/terms",
        status_code=400,
        json={"message": "Bad Request"},
    )
    requests_mock.post(
        f"{api_base}/api/v1/courses/{course_id}/grading_standards",
        status_code=400,
        json={"message": "Bad Request"},
    )

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/{course_id}",
        json={"ok": True},
        status_code=200,
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/{course_id}/settings",
        json={"ok": True},
        status_code=200,
    )
    requests_mock.put(
        re.compile(rf"{api_base}/api/v1/courses/{course_id}/tabs/.*"),
        json={"ok": True},
        status_code=200,
    )

    with caplog.at_level(logging.WARNING):
        import_course_settings(
            target_course_id=course_id,
            export_root=export_root,
            canvas=canvas,
            participation_mode="course",
        )

    assert put_course.called
    assert put_settings.called

    course_payload = put_course.last_request.json()["course"]
    assert course_payload["restrict_enrollments_to_course_dates"] is True
    assert course_payload["grading_standard_enabled"] is False
    assert "grading_standard_id" not in course_payload

    settings_payload = put_settings.last_request.json()
    assert settings_payload["restrict_enrollments_to_course_dates"] is True
    assert settings_payload["restrict_student_future_view"] is True
    assert settings_payload["restrict_student_past_view"] is True
    assert settings_payload["grading_standard_enabled"] is False
    assert "grading_standard_id" not in settings_payload


def test_course_metadata_fallback_on_400(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Fallback Course",
        "course_code": "FC",
        "image_id": 123,
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_id = 557
    course_url = f"{api_base}/api/v1/courses/{course_id}"

    requests_mock.register_uri(
        "PUT",
        course_url,
        [
            {"status_code": 400, "text": "bad course update"},
            {"status_code": 200, "json": {"ok": True}},
        ],
    )
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    import_course_settings(
        target_course_id=course_id,
        export_root=export_root,
        canvas=canvas,
        id_map={"files": {123: 456}},
        auto_set_term=False,
        participation_mode="course",
    )

    calls = [
        req for req in requests_mock.request_history if req.method == "PUT" and req.url == course_url
    ]
    assert len(calls) >= 2
    primary_payload = calls[0].json()["course"]
    fallback_payload = calls[1].json()["course"]

    assert primary_payload["restrict_enrollments_to_course_dates"] is True
    assert fallback_payload["restrict_enrollments_to_course_dates"] is True
    assert fallback_payload["image_id"] == 456
    assert "grading_standard_id" not in fallback_payload
    assert set(fallback_payload.keys()).issubset(
        {
            "restrict_enrollments_to_course_dates",
            "image_id",
            "apply_assignment_group_weights",
            "grading_standard_enabled",
            "start_at",
            "end_at",
        }
    )


def test_course_metadata_retry_without_term(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Retry Course",
        "course_code": "RC",
        "term_id": 2,
        "start_at": "2025-01-01T00:00:00Z",
        "end_at": "2025-04-01T00:00:00Z",
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_id = 558
    course_url = f"{api_base}/api/v1/courses/{course_id}"

    requests_mock.register_uri(
        "PUT",
        course_url,
        [
            {"status_code": 400, "text": "term not found"},
            {"status_code": 200, "json": {"ok": True}},
        ],
    )
    requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    import_course_settings(
        target_course_id=course_id,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="course",
    )

    calls = [
        req for req in requests_mock.request_history if req.method == "PUT" and req.url == course_url
    ]
    assert len(calls) >= 2
    first_payload = calls[0].json()["course"]
    second_payload = calls[1].json()["course"]

    assert first_payload["enrollment_term_id"] == 2
    assert first_payload["start_at"] == "2025-01-01T00:00:00Z"
    assert first_payload["end_at"] == "2025-04-01T00:00:00Z"
    assert "enrollment_term_id" not in second_payload
    assert second_payload["start_at"] == "2025-01-01T00:00:00Z"
    assert second_payload["end_at"] == "2025-04-01T00:00:00Z"


def test_participation_term_mode(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Participation Test",
        "restrict_enrollments_to_course_dates": True,
        "settings": {
            "restrict_enrollments_to_course_dates": True,
            "restrict_student_future_view": True,
            "restrict_student_past_view": True,
        },
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/555", json={"ok": True}, status_code=200
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/555/settings", json={"ok": True}, status_code=200
    )

    import_course_settings(
        target_course_id=555,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="term",
    )

    course_payload = put_course.last_request.json()["course"]
    assert course_payload["restrict_enrollments_to_course_dates"] is False

    settings_payload = put_settings.last_request.json()
    assert settings_payload["restrict_enrollments_to_course_dates"] is False
    assert settings_payload["restrict_student_future_view"] is False
    assert settings_payload["restrict_student_past_view"] is False


def test_participation_inherit_respects_export(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    meta = {
        "name": "Inherited Participation",
        "restrict_enrollments_to_course_dates": False,
        "settings": {
            "restrict_enrollments_to_course_dates": False,
            "restrict_student_future_view": False,
            "restrict_student_past_view": True,
        },
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/556", json={"ok": True}, status_code=200
    )
    put_settings = requests_mock.put(
        f"{api_base}/api/v1/courses/556/settings", json={"ok": True}, status_code=200
    )

    import_course_settings(
        target_course_id=556,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    course_payload = put_course.last_request.json()["course"]
    assert course_payload["restrict_enrollments_to_course_dates"] is False

    settings_payload = put_settings.last_request.json()
    assert settings_payload["restrict_enrollments_to_course_dates"] is False
    assert settings_payload["restrict_student_future_view"] is False
    assert settings_payload["restrict_student_past_view"] is True


def test_override_sis_fields(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    _write(course_dir / "course_metadata.json", json.dumps({"name": "Biology"}))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/555", json={"ok": True}, status_code=200
    )

    import_course_settings(
        target_course_id=555,
        export_root=export_root,
        canvas=canvas,
        id_map={},
        auto_set_term=False,
        participation_mode="inherit",
        sis_course_id="NEW-SIS",
        integration_id="integration-123",
        sis_import_id="import-456",
    )

    body = put_course.last_request.json()
    course_payload = body["course"]
    assert course_payload["sis_course_id"] == "NEW-SIS"
    assert course_payload["integration_id"] == "integration-123"
    assert course_payload["sis_import_id"] == "import-456"


def test_applies_course_navigation(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"

    nav = [
        {"id": "modules", "position": 4, "hidden": False},
        {"id": "assignments", "position": 2, "hidden": True},
    ]
    _write(course_dir / "course_navigation.json", json.dumps(nav))
    _write(course_dir / "course_metadata.json", json.dumps({"name": "Nav Test"}))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/222"
    requests_mock.put(course_url, json={"ok": True}, status_code=200)

    tab_modules = requests_mock.put(
        f"{api_base}/api/v1/courses/222/tabs/modules",
        json={"id": "modules"},
        status_code=200,
    )
    tab_assignments = requests_mock.put(
        f"{api_base}/api/v1/courses/222/tabs/assignments",
        json={"id": "assignments"},
        status_code=200,
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert tab_modules.called
    assert tab_assignments.called
    mod_payload = tab_modules.last_request.json()
    asn_payload = tab_assignments.last_request.json()
    assert asn_payload["position"] == 1
    assert asn_payload.get("hidden") is True
    assert mod_payload["position"] == 2
    assert mod_payload.get("hidden") is False
    assert counts["updated"] >= 3  # course PUT + two tab updates


def test_uploads_course_image_when_missing_id_map(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True, exist_ok=True)

    (course_dir / "course-card.png").write_bytes(b"image-data")

    meta = {
        "name": "Design 200",
        "image_id": 111,
        "course_image_export_path": "course-card.png",
        "course_image_filename": "course-card.png",
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/222",
        json={"ok": True},
        status_code=200,
    )
    requests_mock.post("https://uploads.test/upload", json={"id": 555}, status_code=200)

    id_map = {"files": {}}
    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert put_course.called
    payload = put_course.last_request.json()["course"]
    assert payload["image_id"] == 555
    assert payload["image_url"] is None
    assert id_map["files"][111] == 555
    assert counts["updated"] >= 1


def test_uploads_course_image_without_original_id(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True, exist_ok=True)

    (course_dir / "course-image.jpg").write_bytes(b"image-data")

    meta = {
        "name": "History 101",
        "course_image_export_path": "course-image.jpg",
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/333",
        json={"ok": True},
        status_code=200,
    )
    requests_mock.post("https://uploads.test/upload", json={"id": 777}, status_code=200)

    counts = import_course_settings(
        target_course_id=333,
        export_root=export_root,
        canvas=canvas,
        id_map={},
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert put_course.called
    payload = put_course.last_request.json()["course"]
    assert payload["image_id"] == 777
    assert payload["image_url"] is None
    assert counts["updated"] >= 1


def test_maps_grading_standard_with_id_map(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "name": "Course With Scheme",
        "grading_standard_enabled": True,
        "grading_standard_id": 5017,
        "settings": {"grading_standard_enabled": True, "grading_standard_id": 5017},
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/222"
    put_course = requests_mock.put(course_url, json={"ok": True}, status_code=200)
    put_settings = requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    id_map = {"grading_standards": {5017: 9009}}

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert put_course.called
    assert put_settings.called
    payload = put_course.last_request.json()["course"]
    assert payload["grading_standard_id"] == 9009
    assert payload["grading_standard_enabled"] is True
    settings_payload = put_settings.last_request.json()
    assert settings_payload["grading_standard_id"] == 9009
    assert settings_payload["grading_standard_enabled"] is True
    assert counts["updated"] >= 2


def test_creates_grading_standard_when_missing_map(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    course_dir = export_root / "course"
    course_dir.mkdir(parents=True, exist_ok=True)

    grading_standard = {
        "id": 5017,
        "title": "Imported Scheme",
        "grading_scheme": [
            {"name": "A", "value": 0.9},
            {"name": "B", "value": 0.8},
        ],
    }
    meta = {
        "name": "Course With Scheme",
        "grading_standard_enabled": True,
        "grading_standard_id": 5017,
        "grading_standard": grading_standard,
        "settings": {"grading_standard_enabled": True, "grading_standard_id": 5017},
    }
    _write(course_dir / "course_metadata.json", json.dumps(meta))

    api_base = "https://api.example.edu"
    canvas = DummyCanvas(api_base)

    course_url = f"{api_base}/api/v1/courses/222"
    put_course = requests_mock.put(course_url, json={"ok": True}, status_code=200)
    put_settings = requests_mock.put(f"{course_url}/settings", json={"ok": True}, status_code=200)

    post_standard = requests_mock.post(
        f"{api_base}/api/v1/courses/222/grading_standards",
        json={"id": 7777},
        status_code=200,
    )

    id_map: Dict[str, Dict[Any, Any]] = {}

    import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        id_map=id_map,
        auto_set_term=False,
        participation_mode="inherit",
    )

    assert post_standard.called
    payload = post_standard.last_request.json()["grading_standard"]
    assert payload["title"] == "Imported Scheme"
    assert payload["grading_scheme"][0]["value"] == 0.9
    course_payload = put_course.last_request.json()["course"]
    assert course_payload["grading_standard_id"] == 7777
    assert course_payload["grading_standard_enabled"] is True
    assert id_map["grading_standards"]["5017"] == 7777
