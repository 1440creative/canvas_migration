# importers/import_blueprint.py

from __future__ import annotations
from pathlib import Path
import json
import requests
from typing import Protocol, Dict, Any
from logging_setup import get_logger

class CanvasLike(Protocol):
    def get(self, endpoint: str, params: dict|None=None) -> Dict[str, Any]: ...
    def put(self, endpoint: str, *, json: Dict[str, Any]|None=None, data=None, files=None, params=None): ...

def _read_export_flag(export_root: Path) -> bool:
    """
    Read whatever your exporter wrote for blueprint-ness.
    Adjust the filename/shape to match your export (examples below).
    """
    # Try a couple of likely locations/names
    candidates = [
        export_root / "course" / "blueprint.json",
        export_root / "course" / "blueprint_settings.json",
        export_root / "course" / "settings.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8"))
            except Exception:
                continue
            # Accept common shapes from exporters
            if isinstance(data, dict):
                if "blueprint" in data:
                    return bool(data["blueprint"])
                if "is_blueprint_course" in data:
                    return bool(data["is_blueprint_course"])
                if "course" in data and isinstance(data["course"], dict):
                    c = data["course"]
                    if "blueprint" in c: return bool(c["blueprint"])
                    if "is_blueprint_course" in c: return bool(c["is_blueprint_course"])
    return False

def ensure_blueprint_enabled(target_course_id: int, api: CanvasLike) -> bool:
    """
    Try to enable Blueprint on the target course. Returns True if enabled.
    """
    log = get_logger(artifact="blueprint", course_id=target_course_id)

    # First: check current state
    try:
        course = api.get(f"/api/v1/courses/{target_course_id}")
        if bool(course.get("blueprint")):
            log.info("Course already a Blueprint course")
            return True
    except Exception as e:
        log.warning("Could not fetch course to check blueprint state: %s", e)

    # Try the two known payload shapes used by Canvas
    attempts = [
        {"course": {"is_blueprint_course": True}},
        {"course": {"blueprint": True}},
    ]
    for payload in attempts:
        try:
            r = api.put(f"/api/v1/courses/{target_course_id}", json=payload)
            r.raise_for_status()
            # Re-check
            course = api.get(f"/api/v1/courses/{target_course_id}")
            if bool(course.get("blueprint")):
                log.info("Enabled Blueprint on target course")
                return True
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "")[:400]
            log.debug("Enable blueprint attempt failed payload=%s status=%s body=%r",
                      payload, getattr(e.response, "status_code", "?"), body)
        except Exception as e:
            log.debug("Enable blueprint attempt failed payload=%s err=%s", payload, e)

    log.error("Could not enable Blueprint on the target course. "
              "Ensure the account feature is enabled and the token has permission.")
    return False

def import_blueprint_settings(*, target_course_id: int, export_root: Path, api: CanvasLike) -> None:
    """
    Minimal: ensures target is a Blueprint course if source was.
    (You can extend this to apply lockable restrictions/sync rules next.)
    """
    log = get_logger(artifact="blueprint", course_id=target_course_id)

    source_was_blueprint = _read_export_flag(export_root)
    if not source_was_blueprint:
        log.info("Source was not a Blueprint course (nothing to do).")
        return

    if ensure_blueprint_enabled(target_course_id, api):
        log.info("Blueprint state mirrored from source → target")
    else:
        log.error("Blueprint state could not be set; continuing without it.")
