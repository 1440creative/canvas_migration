# export/export_blueprint_settings.py
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, List
import requests
from logging_setup import get_logger

class CanvasLike(Protocol):
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any: ...
    api_root: str
    session: requests.Session

def export_blueprint_settings(course_id: int, export_root: Path, api: CanvasLike) -> Dict[str, Any]:
    log = get_logger(artifact="blueprint_export", course_id=course_id)
    out_dir = export_root / str(course_id) / "course"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "blueprint.json"

    data: Dict[str, Any] = {
        "course_id": course_id,
        "is_blueprint": False,
        "templates": [],
        "exported_at": int(time.time()),
    }

    # 1) Try to list blueprint templates (authoritative when permitted)
    try:
        templates = api.get(f"/api/v1/courses/{course_id}/blueprint_templates")
        if isinstance(templates, list) and templates:
            data["is_blueprint"] = True
            data["templates"] = templates
            out_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            log.info("Exported blueprint templates", extra={"count": len(templates), "path": str(out_file)})
            return data
        # empty list → either not a blueprint or no template created yet
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        body = (e.response.text[:300] if getattr(e, "response", None) is not None else "")
        log.warning("Blueprint template list not accessible", extra={"status": status, "body": body})

    # 2) Fallback probe: check course flags for blueprint
    try:
        course = api.get(f"/api/v1/courses/{course_id}", params={"include[]": ["is_blueprint"]})
        is_bp = bool(course.get("is_blueprint") or course.get("blueprint"))
        data["is_blueprint"] = is_bp
    except Exception as e:
        log.warning("Could not probe course.is_blueprint: %s", e)

    out_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    if data["is_blueprint"]:
        log.info("Course is Blueprint but templates not readable; wrote minimal metadata", extra={"path": str(out_file)})
    else:
        log.info("No blueprint templates or not permitted; wrote %s", str(out_file))

    return data
