# export/export_blueprint_settings.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import requests
from logging_setup import get_logger
from utils.api import DEFAULT_TIMEOUT


class CanvasLike(Protocol):
    api_root: str
    session: requests.Session


def _get_json(sess: requests.Session, url: str) -> Any:
    r = sess.get(url, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {}


def _ids_only(items: Any) -> List[int]:
    """Normalize a list of course dicts/ids into a flat list of ints."""
    out: List[int] = []
    if isinstance(items, list):
        for x in items:
            if isinstance(x, dict) and "id" in x:
                try:
                    out.append(int(x["id"]))
                except Exception:
                    pass
            else:
                try:
                    out.append(int(x))
                except Exception:
                    pass
    return out


def export_blueprint_settings(course_id: int, export_root: Path, api: CanvasLike) -> Dict[str, Any]:
    """
    Export Blueprint metadata into:
      <export_root>/<course_id>/blueprint/blueprint_metadata.json

    Returns {} for non-blueprint courses (and does NOT write anything).
    """
    log = get_logger(artifact="blueprint_export", course_id=course_id)

    # Detect blueprint from /courses/:id/settings (tests mock this)
    settings_url = f"{api.api_root}courses/{course_id}/settings"
    try:
        settings = _get_json(api.session, settings_url)
    except Exception as e:
        log.warning("Could not fetch course settings for blueprint check: %s", e)
        return {}

    is_blueprint = bool(settings.get("blueprint") is True)
    if not is_blueprint:
        # Tests expect meta == {} and nothing written
        return {}

    # Gather template info (best-effort)
    templates: List[Dict[str, Any]] = []
    chosen_template: Optional[Dict[str, Any]] = None

    try:
        list_url = f"{api.api_root}courses/{course_id}/blueprint_templates"
        listed = _get_json(api.session, list_url)

        # Normalize into a list of template IDs (the API can return a list or a single object)
        template_ids: List[int] = []
        if isinstance(listed, list):
            for t in listed:
                tid = t.get("id")
                try:
                    template_ids.append(int(tid))
                except Exception:
                    continue
        elif isinstance(listed, dict) and "id" in listed:
            try:
                template_ids.append(int(listed["id"]))
            except Exception:
                pass

        for tid in template_ids:
            # detail
            detail_url = f"{api.api_root}courses/{course_id}/blueprint_templates/{tid}"
            try:
                detail = _get_json(api.session, detail_url)
            except Exception:
                detail = {}

            # restrictions (optional)
            restr_url = f"{api.api_root}courses/{course_id}/blueprint_templates/{tid}/restrictions"
            try:
                restrictions = _get_json(api.session, restr_url)
            except Exception:
                restrictions = {}

            # associated courses (optional)
            assoc_url = f"{api.api_root}courses/{course_id}/blueprint_templates/{tid}/associated_courses"
            try:
                associated = _get_json(api.session, assoc_url)
            except Exception:
                associated = []

            entry = {
                "id": int(tid),
                "name": detail.get("name") or "default",
                "default": bool(detail.get("default")),
                "restrictions": restrictions,
                "associated_courses": _ids_only(associated),
            }
            templates.append(entry)

    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status in (401, 403, 404):
            log.warning("Blueprint template list not accessible")
        else:
            log.warning("Error fetching blueprint templates: %s", e)
    except Exception as e:
        log.warning("Unexpected error fetching blueprint templates: %s", e)

    # Choose the default template (or the first one) for meta["template"]
    if templates:
        chosen_template = next((t for t in templates if t.get("default")), None) or templates[0]

    # Prepare doc
    doc: Dict[str, Any] = {
        "course_id": int(course_id),
        "is_blueprint": True,
        "templates": templates,  # may be empty if unreadable
    }
    if chosen_template is not None:
        doc["template"] = chosen_template
        # Tests expect a TOP-LEVEL array of associated course IDs too
        doc["associated_courses"] = chosen_template.get("associated_courses", [])
    else:
        doc["associated_courses"] = []

    # Write file
    out_dir = export_root / str(course_id) / "blueprint"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "blueprint_metadata.json"
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if templates:
        log.info("Exported blueprint metadata with %d template(s)", len(templates))
    else:
        log.info("Exported blueprint metadata without template details (limited access)")

    return doc
