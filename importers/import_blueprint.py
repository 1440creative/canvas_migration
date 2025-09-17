# importers/import_blueprint.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, Dict, Any

import requests
from logging_setup import get_logger

class CanvasLike(Protocol):
    api_root: str
    session: requests.Session
    def get(self, endpoint: str, params: Dict[str, Any] | None = None) -> Dict[str, Any] | list: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...

def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def import_blueprint_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
) -> None:
    log = get_logger(artifact="blueprint", course_id=target_course_id)

    bp_path = export_root / "course" / "blueprint.json"
    meta = _read_json(bp_path)

    # Fast exit if we don’t even have the export flag
    if not meta:
        log.info("No blueprint.json found; nothing to import.")
        return

    # Interpret any of a few flags the exporter might set
    flags = {
        "is_blueprint": bool(meta.get("is_blueprint")),
        "is_blueprint_course": bool(meta.get("is_blueprint_course")),
        "blueprint": bool(meta.get("blueprint")),
        "course.is_blueprint_course": bool(meta.get("course.is_blueprint_course")),
    }
    log.debug("blueprint.json flags=%s", flags)

    src_was_blueprint = any(flags.values())
    if not src_was_blueprint:
        log.info("Source was not a Blueprint course (nothing to do).")
        return

    # 1) Enable Blueprint on the target course
    # Try JSON first, then fall back to form-encoded (Canvas is picky on some tenants)
    enable_url = f"/api/v1/courses/{target_course_id}"
    json_payload = {"course": {"is_blueprint_course": True}}
    form_payload = {"course[is_blueprint_course]": "true"}

    # Attempt A: JSON
    try:
        r = canvas.put(enable_url, json=json_payload)
        # Requests-compatible response: raise if not 2xx
        r.raise_for_status()
    except Exception as e:
        # Attempt B: form-encoded
        try:
            r2 = canvas.put(enable_url, data=form_payload)
            r2.raise_for_status()
            r = r2
        except Exception as e2:
            body = getattr(getattr(e2, "response", None), "text", "") or ""
            log.error("Failed to enable Blueprint (both JSON & form). %s %s", type(e2).__name__, str(e2))
            if body:
                log.error("Response body: %s", body[:600])
            return

    log.info("Enabling Blueprint on target course %s", target_course_id)

    # 2) Verify the flag actually stuck
    try:
        course = canvas.get(f"/api/v1/courses/{target_course_id}")
        is_bp = bool(course.get("is_blueprint_course"))
    except Exception as e:
        log.warning("Could not verify Blueprint status after update: %s", e)
        is_bp = False

    if not is_bp:
        log.error("Blueprint flag did not apply (course.is_blueprint_course is false after update).")
        log.error("Check that your token/role can 'Manage (update) course settings' and 'Manage Blueprint Courses'.")
        return

    # 3) Optional: try to list templates (helps us queue sync later if needed)
    try:
        templates = canvas.get(f"/api/v1/courses/{target_course_id}/blueprint_templates", params={"per_page": 100})
        # Not all tokens can read templates immediately; that’s okay.
    except Exception as e:
        log.debug("Could not list blueprint templates: %s", e)
        templates = []

    if templates:
        log.debug("Blueprint templates present: %s", [t.get("id") for t in templates])
    else:
        log.debug("No templates visible (course just enabled or insufficient permission).")

    log.info("Blueprint import step complete.")
