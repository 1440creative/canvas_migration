# tests/test_import_course_settings_blueprint.py
import json
import importlib.util
from pathlib import Path
import requests

from tests.conftest import DummyCanvas

def _load_module(project_root: Path):
    mod_path = (project_root / "importers" / "import_course_settings.py").resolve()
    assert mod_path.exists(), f"Expected module at {mod_path}"
    spec = importlib.util.spec_from_file_location("import_course_settings_mod", str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Could not build spec for {mod_path}"
    spec.loader.exec_module(mod)
    assert hasattr(mod, "import_course_settings") and callable(mod.import_course_settings), \
        "import_course_settings not found or not callable"
    return mod


def test_import_course_settings_blueprint_fields_and_sync(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    cdir = export_root / "course"
    cdir.mkdir(parents=True)

    (cdir / "course_metadata.json").write_text(json.dumps({
        "name": "BP Course",
        "course_code": "BP-101",
        "blueprint": True,
        "blueprint_restrictions": {"content": "locked"},
        "use_blueprint_restrictions_by_object_type": True,
        "blueprint_restrictions_by_object_type": {
            "assignment": {"content": "locked"}
        },
        "settings": {"default_view": "modules"}
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    # Mock the three endpoints
    requests_mock.put(f"{api_base}/api/v1/courses/222", json={"id": 222}, status_code=200)
    requests_mock.put(f"{api_base}/api/v1/courses/222/settings", json={"ok": True}, status_code=200)
    requests_mock.post(f"{api_base}/api/v1/courses/222/blueprint_templates/default/migrations",
                       json={"migration_id": 1}, status_code=200)

    mod = _load_module(Path.cwd())
    canvas = DummyCanvas(api_base)

    mod.import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
        auto_set_term=False,
        force_course_dates=False,
        queue_blueprint_sync=True,
        blueprint_sync_options={"send_notification": True, "comment": "Sync me"},
    )

    # Validate URLs were hit
    hist = requests_mock.request_history
    urls = [h.url for h in hist]
    assert f"{api_base}/api/v1/courses/222" in urls
    assert f"{api_base}/api/v1/courses/222/settings" in urls
    assert f"{api_base}/api/v1/courses/222/blueprint_templates/default/migrations" in urls

    # Validate course payload contains blueprint fields under "course"
    course_req = next(h for h in hist if h.method == "PUT" and h.url.endswith("/api/v1/courses/222"))
    body = course_req.json()
    course = body.get("course", {})
    assert course.get("blueprint") is True
    assert course.get("blueprint_restrictions") == {"content": "locked"}
    assert course.get("use_blueprint_restrictions_by_object_type") is True
    assert course.get("blueprint_restrictions_by_object_type") == {
        "assignment": {"content": "locked"}
    }

    # Validate blueprint sync payload
    sync_req = next(h for h in hist if h.method == "POST" and h.url.endswith("/migrations"))
    sync_body = sync_req.json()
    # copy_settings defaults to True in the importer
    assert sync_body.get("copy_settings") is True
    assert sync_body.get("send_notification") is True
    assert sync_body.get("comment") == "Sync me"
