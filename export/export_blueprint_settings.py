# export/export_blueprint_settings.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable


def export_blueprint_settings(course_id: int, export_root: Path, api: CanvasAPI) -> Dict[str, Any]:
    """
    Export Blueprint template + lock rules if the course is a Blueprint.
    - Writes:
        export/data/{course_id}/blueprint/blueprint_metadata.json
    - Returns {} if not blueprint or no template found.
    """
    log = get_logger(artifact="blueprint", course_id=course_id)

    # Quick check via settings
    settings = api.get(f"courses/{course_id}/settings")
    if not isinstance(settings, dict):
        return {}

    is_blueprint = bool(settings.get("blueprint") or settings.get("is_blueprint") or settings.get("blueprint_restrictions"))
    if not is_blueprint:
        log.info("course is not a blueprint; skipping")
        return {}

    out_dir = (export_root / str(course_id) / "blueprint")
    ensure_dir(out_dir)

    # Try default template first
    # (accept both with/without /api/v1 due to normalized API root)
    templates = api.get(f"courses/{course_id}/blueprint_templates")
    template_id = None
    if isinstance(templates, list) and templates:
        # Prefer the default, otherwise first in sorted order
        default = next((t for t in templates if t.get("default")), None)
        tpl = default or sorted(templates, key=lambda t: (not t.get("default", False), t.get("id") or 0))[0]
        template_id = tpl.get("id")

    # If no list available, some instances support 'default' endpoint directly
    if template_id is None:
        try:
            default_tpl = api.get(f"courses/{course_id}/blueprint_templates/default")
            if isinstance(default_tpl, dict):
                template_id = default_tpl.get("id")
        except Exception:
            template_id = None

    if template_id is None:
        log.info("no blueprint template found")
        # still write a small file indicating blueprint=true but no template id
        atomic_write(out_dir / "blueprint_metadata.json", json_dumps_stable({
            "is_blueprint": True, "template": None, "restrictions": None,
            "associated_courses": None,
            "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/blueprint_templates"
        }))
        return {}

    # Pull template detail + restrictions + associated courses (where supported)
    template = api.get(f"courses/{course_id}/blueprint_templates/{template_id}")
    restrictions = None
    try:
        # Some deployments expose granular restrictions via this path
        restrictions = api.get(f"courses/{course_id}/blueprint_templates/{template_id}/restrictions")
    except Exception:
        restrictions = None

    associated_courses = None
    try:
        ac = api.get(f"courses/{course_id}/blueprint_templates/{template_id}/associated_courses")
        if isinstance(ac, list):
            # Save minimal info (ids), not full course objects, to stay light
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
        "restrictions": restrictions if isinstance(restrictions, dict) else None,
        "associated_courses": associated_courses,
        "source_api_url": api.api_root.rstrip("/") + f"/courses/{course_id}/blueprint_templates/{template_id}",
    }
    atomic_write(out_dir / "blueprint_metadata.json", json_dumps_stable(meta))
    log.info("exported blueprint template + restrictions", extra={"template_id": template_id})
    return meta
