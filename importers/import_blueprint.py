from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import requests
from logging_setup import get_logger

class CanvasLike(Protocol):
    api_root: str
    session: requests.Session
    def get(self, endpoint: str, **kwargs) -> Any: ...
    def post(self, endpoint: str, **kwargs) -> Any: ...
    def put(self, endpoint: str, **kwargs) -> Any: ...

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
    """
    Enable Blueprint on the target if the source export indicates it.
    Reads: <export_root>/course/blueprint.json
    """
    log = get_logger(artifact="blueprint", course_id=target_course_id)

    bp_path = export_root / "course" / "blueprint.json"
    if not bp_path.exists():
        log.info("No blueprint.json found under %s; nothing to do.", bp_path.parent)
        return

    meta = _read_json(bp_path)
    # Accept any of the common flags that might be written by different exporters
    is_bp = bool(
        meta.get("is_blueprint")
        or meta.get("is_blueprint_course")
        or meta.get("blueprint")
        or (meta.get("course") or {}).get("is_blueprint_course")
    )

    log.debug("blueprint.json flags=%r", {
        "is_blueprint": meta.get("is_blueprint"),
        "is_blueprint_course": meta.get("is_blueprint_course"),
        "blueprint": meta.get("blueprint"),
        "course.is_blueprint_course": (meta.get("course") or {}).get("is_blueprint_course"),
    })

    if not is_bp:
        log.info("Source was not a Blueprint course (nothing to do).")
        return

    # Check current target status (best-effort)
    try:
        curr = canvas.get(f"/api/v1/courses/{target_course_id}")
        already_bp = bool(curr.get("is_blueprint_course") or curr.get("blueprint"))
    except Exception:
        already_bp = False

    if already_bp:
        log.info("Target course already Blueprint-enabled.")
        return

    log.info("Enabling Blueprint on target course %s", target_course_id)
    resp = canvas.put(
        f"/api/v1/courses/{target_course_id}",
        json={"course": {"is_blueprint_course": True}},
    )
    try:
        _ = resp.json()  # just to surface parse issues in logs if any
    except Exception:
        pass

    # Optional: try listing templates (not required to succeed)
    try:
        tmpls = canvas.get(f"/api/v1/courses/{target_course_id}/blueprint_templates")
        if isinstance(tmpls, list) and tmpls:
            log.info("Blueprint enabled; %d template(s) visible.", len(tmpls))
        else:
            log.info("Blueprint enabled; no templates visible (may be fine).")
    except Exception as e:
        log.debug("Could not list blueprint templates: %s", e)
