# export/export_blueprint_settings.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable


def export_blueprint_settings(course_id: int, export_root: Path, api: CanvasAPI) -> Dict[str, Any]:
    """
    Export Blueprint template + lock rules if the course is a Blueprint.
    Writes: export/data/{course_id}/blueprint/blueprint_metadata.json
    Returns {} if definitively not a blueprint.
    """
    log = get_logger(artifact="blueprint", course_id=course_id)
    out_dir = export_root / str(course_id) / "blueprint"

    # 1) Check both course and settings for the flag
    course: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    try:
        c = api.get(f"courses/{course_id}")
        if isinstance(c, dict):
            course = c
    except Exception:
        pass
    try:
        s = api.get(f"courses/{course_id}/settings")
        if isinstance(s, dict):
            settings = s
    except Exception:
        pass

    flags = [
        course.get("blueprint"),
        course.get("is_blueprint"),
        settings.get("blueprint"),
        settings.get("is_blueprint"),
        bool(settings.get("blueprint_restrictions")),
    ]
    is_blueprint = any(bool(x) for x in flags)

    # 2) Probe templates endpoint to confirm/override
    templates: Optional[List[Dict[str, Any]]] = None
    templates_error: Optional[str] = None
    try:
        t = api.get(f"courses/{course_id}/blueprint_templates")
        if isinstance(t, list):
            templates = t
        elif isinstance(t, dict):  # some instances return an object
            templates = [t]
        if templates and not is_blueprint:
            is_blueprint = True  # infer from accessible templates
    except Exception as e:
        templates_error = type(e).__name__

    if not is_blueprint:
        log.info("course is not a blueprint; skipping")
        return {}

    ensure_dir(out_dir)

    # 3) Choose a template id (prefer 'default', else the first by id)
    template_id: Optional[int] = None
    if templates:
        default = next((t for t in templates if t.get("default")), None)
        chosen = default or sorted(templates, key=lambda t: t.get("id") or 0)[0]
        template_id = chosen.get("id")

    # Fallback: try 'default' endpoint if no list or no id
    if template_id is None:
        try:
            default_tpl = api.get(f"courses/{course_id}/blueprint_templates/default")
            if isinstance(default_tpl, dict):
                template_id = default_tpl.get("id")
                # populate minimal templates info for logging/metadata
                templates = [default_tpl]
        except Exception:
            pass

    # 4) If we still don't have a template id, write minimal metadata and exit
    if template_id is None:
        atomic_write(out_dir / "blueprint_metadata.json", json_dumps_stable({
            "is_blueprint": True,
            "template": None,
            "restrictions": None,
            "associated_courses": None,
            "probe_error": templates_error,  # e.g., 'HTTPError' if permissions block the list
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/blueprint_templates"
        }))
        log.info("blueprint detected but no template list/ID available (likely permissions); metadata written")
        return {"is_blueprint": True, "template": None}

    # 5) Fetch details (best-effort)
    template = None
    restrictions = None
    associated_courses = None
    try:
        template = api.get(f"courses/{course_id}/blueprint_templates/{template_id}")
    except Exception:
        template = {"id": template_id}

    try:
        restrictions = api.get(f"courses/{course_id}/blueprint_templates/{template_id}/restrictions")
        if not isinstance(restrictions, dict):
            restrictions = None
    except Exception:
        restrictions = None

    try:
        ac = api.get(f"courses/{course_id}/blueprint_templates/{template_id}/associated_courses")
        if isinstance(ac, list):
            associated_courses = sorted([c.get("id") for c in ac if isinstance(c.get("id"), int)])
    except Exception:
        associated_courses = None

    meta: Dict[str, Any] = {
        "is_blueprint": True,
        "template": {
            "id": template.get("id") if isinstance(template, dict) else template_id,
            "name": (template or {}).get("name") if isinstance(template, dict) else None,
            "default": (template or {}).get("default") if isinstance(template, dict) else None,
        },
        "restrictions": restrictions,
        "associated_courses": associated_courses,
        "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/blueprint_templates/{template_id}",
    }
    atomic_write(out_dir / "blueprint_metadata.json", json_dumps_stable(meta))
    log.info("exported blueprint template + restrictions", extra={"template_id": template_id})
    return meta
