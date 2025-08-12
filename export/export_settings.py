# export/export_settings.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable


def export_course_settings(course_id: int, export_root: Path, api: CanvasAPI) -> Dict[str, Any]:
    """
    Export high-level course info + the settings blob.
    - Writes:
        export/data/{course_id}/course/course_metadata.json
        export/data/{course_id}/course/course_settings.json
    - Returns a small dict summary (includes blueprint flag).
    """
    log = get_logger(artifact="course_settings", course_id=course_id)

    course_root = export_root / str(course_id)
    out_dir = course_root / "course"
    ensure_dir(out_dir)

    # Basic course info (metadata)
    course = api.get(f"courses/{course_id}")
    if not isinstance(course, dict):
        raise TypeError("Expected course dict from Canvas API")

    metadata = {
        "id": course.get("id"),
        "uuid": course.get("uuid"),
        "sis_course_id": course.get("sis_course_id"),
        "name": course.get("name"),
        "course_code": course.get("course_code"),
        "term_id": (course.get("enrollment_term_id") or course.get("term", {}).get("id")),
        "account_id": course.get("account_id"),
        "workflow_state": course.get("workflow_state"),
        "start_at": course.get("start_at"),
        "end_at": course.get("end_at"),
        "is_blueprint": bool(course.get("blueprint") or course.get("is_blueprint")),
        "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}",
    }
    atomic_write(out_dir / "course_metadata.json", json_dumps_stable(metadata))

    # Course settings blob
    settings = api.get(f"courses/{course_id}/settings")
    if not isinstance(settings, dict):
        raise TypeError("Expected settings dict from Canvas API")

    atomic_write(out_dir / "course_settings.json", json_dumps_stable(settings))

    log.info("exported course info + settings", extra={"is_blueprint": metadata["is_blueprint"]})
    return {"is_blueprint": metadata["is_blueprint"]}
