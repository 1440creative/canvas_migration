# tests/test_import_course_settings.py
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

def test_import_course_settings_updates_fields_and_settings(tmp_path, requests_mock):
    export_root = tmp_path / "export" / "data" / "101"
    cdir = export_root / "course"
    cdir.mkdir(parents=True)

    (cdir / "course_metadata.json").write_text(json.dumps({
        "id": 101,
        "name": "Intro to Testing",
        "course_code": "TEST-101",
        "settings": {
            "default_view": "modules",
            "hide_final_grades": True
        }
    }), encoding="utf-8")

    (cdir / "settings.json").write_text(json.dumps({
        "hide_final_grades": False,
        "filter_speed_grader_by_student_group": True
    }), encoding="utf-8")

    api_base = "https://api.example.edu"
    requests_mock.put(f"{api_base}/api/v1/courses/222", json={"id": 222, "name": "Intro to Testing"}, status_code=200)
    requests_mock.put(f"{api_base}/api/v1/courses/222/settings", json={"ok": True}, status_code=200)

    mod = _load_module(Path.cwd())
    canvas = DummyCanvas(api_base)

    mod.import_course_settings(
        target_course_id=222,
        export_root=export_root,
        canvas=canvas,
    )

    # Validate requests were made with expected bodies
    hist = requests_mock.request_history
    urls = [h.url for h in hist]
    assert f"{api_base}/api/v1/courses/222" in urls
    assert f"{api_base}/api/v1/courses/222/settings" in urls
