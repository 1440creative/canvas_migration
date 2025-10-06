# tests/test_import_course_settings.py
import json
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
        force_course_dates=False,
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
        force_course_dates=False,
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
        force_course_dates=False,
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
        force_course_dates=False,
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
        force_course_dates=False,
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
        force_course_dates=False,
        id_map=id_map,
    )

    assert group_matcher.called
    payload = group_matcher.last_request.json()["assignment_group"]
    assert payload["group_weight"] == 35.0


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
        force_course_dates=False,
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
        json={"enrollment_terms": [{"id": 321, "name": "Default"}]},
        status_code=200,
    )

    counts = import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        target_account_id=54,
        term_name="Default",
        force_course_dates=False,
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
        force_course_dates=False,
    )

    assert counts["updated"] >= 1
    assert put_course.called
    body = put_course.last_request.json()
    assert body["course"]["image_id"] == 999
    assert body["course"]["image_url"] is None


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
        json={"enrollment_terms": [{"id": 314, "name": "Default"}]},
        status_code=200,
    )

    put_course = requests_mock.put(
        f"{api_base}/api/v1/courses/444", json={"ok": True}, status_code=200
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
        force_course_dates=False,
        sis_course_id="NEW-SIS",
        integration_id="integration-123",
        sis_import_id="import-456",
    )

    body = put_course.last_request.json()
    course_payload = body["course"]
    assert course_payload["sis_course_id"] == "NEW-SIS"
    assert course_payload["integration_id"] == "integration-123"
    assert course_payload["sis_import_id"] == "import-456"
