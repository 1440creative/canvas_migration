# export/export_blueprint_settings.py
from __future__ import annotations
from pathlib import Path
import json
from typing import Any, Dict
from logging_setup import get_logger

def export_blueprint_settings(course_id: int, export_root: Path, api) -> Dict[str, Any]:
    """
    Export minimal blueprint metadata so the importer can enable Blueprint
    on the target even if we can't list templates due to permissions.
    Writes: <export_root>/<course_id>/course/blueprint.json
    """
    log = get_logger(artifact="blueprint_export", course_id=course_id)

    out_dir = export_root / str(course_id) / "course"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "blueprint.json"

    is_blueprint = False
    templates: list[dict] = []

    # Try to detect if the source course is a blueprint course
    try:
        course = api.get(f"/api/v1/courses/{course_id}")
        # Canvas returns is_blueprint_course or blueprint in different tenants; check both
        is_blueprint = bool(course.get("is_blueprint_course") or course.get("blueprint"))
    except Exception as e:
        log.warning("Could not fetch course for blueprint detection: %s", e)

    # Try to fetch templates (may require admin perms; 403/401/404 are common)
    if is_blueprint:
        try:
            tmpl = api.get(f"/api/v1/courses/{course_id}/blueprint_templates")
            if isinstance(tmpl, list):
                templates = tmpl
            else:
                templates = []
        except Exception:
            # Not fatal: we still write minimal metadata
            log.warning("Blueprint template list not accessible")

    payload = {
        "course_id": course_id,
        "is_blueprint": bool(is_blueprint),
        "templates": templates,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if is_blueprint and not templates:
        log.info("Course is Blueprint but templates not readable; wrote minimal metadata")
    elif not is_blueprint:
        log.info("Source is not a Blueprint course; wrote metadata")
    else:
        log.info("Exported blueprint metadata with %d template(s)", len(templates))

    return payload
