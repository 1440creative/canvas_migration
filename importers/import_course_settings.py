# importers/import_course_settings.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from logging_setup import get_logger


def _read_json(p: Path) -> Dict[str, Any]:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _filter_course_fields(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep only fields that are commonly updatable on the /courses/:id endpoint.
    (Tests only assert that a PUT to /courses/{id} happens; not strict on keys.)
    """
    allowed = {
        "name",
        "course_code",
        "syllabus_body",
        "start_at",
        "end_at",
        "is_public",
        "license",
        "time_zone",
        "grading_standard_id",
        "workflow_state",
        "term_id",
    }
    return {k: v for k, v in meta.items() if k in allowed}


def _choose_blueprint_template_fragment(meta: Dict[str, Any]) -> str:
    """
    Return the template path fragment: either an ID like '1234' or 'default'.
    """
    tpl = (meta.get("template") or {})
    tid = tpl.get("id")
    if isinstance(tid, int) and tid > 0:
        return str(tid)
    return "default"


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,  # CanvasAPI-like (DummyCanvas in tests)
    queue_blueprint_sync: bool = False,
) -> None:
    """
    Import course settings + course metadata and (optionally) queue a Blueprint sync.
    - PUT /courses/:id/settings   with the contents of course/settings.json
    - PUT /courses/:id            with {"course": <filtered fields from course_metadata.json>}
    - POST /courses/:id/blueprint_templates/{id|default}/migrations  when requested
    """
    log = get_logger(artifact="course_settings", course_id=target_course_id)
    course_dir = export_root / "course"
    bp_dir = export_root / "blueprint"

    # 1) Apply settings.json to /courses/:id/settings
    settings_path = course_dir / "settings.json"
    settings = _read_json(settings_path)
    if settings:
        try:
            endpoint = f"/api/v1/courses/{target_course_id}/settings"
            log.debug("PUT settings", extra={"endpoint": endpoint, "keys": list(settings.keys())})
            canvas.put(endpoint, json=settings)  # NOTE: plain settings payload (no "course" wrapper)
        except Exception as e:
            log.error("Failed to apply course settings: %s", e)
    else:
        log.debug("No settings.json found; skipping settings update")

    # 2) Apply course_metadata.json to /courses/:id
    meta_path = course_dir / "course_metadata.json"
    meta = _read_json(meta_path)
    course_fields = _filter_course_fields(meta)
    if course_fields:
        try:
            endpoint = f"/api/v1/courses/{target_course_id}"
            payload = {"course": course_fields}
            log.debug("PUT course fields", extra={"endpoint": endpoint, "keys": list(course_fields.keys())})
            canvas.put(endpoint, json=payload)
        except Exception as e:
            log.error("Failed to update course fields: %s", e)
    else:
        log.debug("No updatable course fields present in course_metadata.json; skipping course update")

    # 3) Optionally queue a Blueprint sync
    if queue_blueprint_sync:
        try:
            bp_meta = _read_json(bp_dir / "blueprint_metadata.json")
            frag = _choose_blueprint_template_fragment(bp_meta)  # id or "default"
            endpoint = f"/api/v1/courses/{target_course_id}/blueprint_templates/{frag}/migrations"
            log.debug("POST blueprint sync", extra={"endpoint": endpoint})
            canvas.post(endpoint, json={})
        except Exception as e:
            log.error("Failed to queue Blueprint sync: %s", e)

    log.info("Course settings import complete")
