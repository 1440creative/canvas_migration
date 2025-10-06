from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from logging_setup import get_logger

# Safe module-level logger (no course id at import time)
log = get_logger(artifact="course_settings", course_id="-")


_TERM_CACHE: Dict[Tuple[int, str], Optional[int]] = {}


def _detect_weighted_assignment_groups(export_root: Path) -> Optional[bool]:
    groups_dir = export_root / "assignment_groups"
    if not groups_dir.exists():
        return None

    for meta_path in groups_dir.rglob("assignment_group_metadata.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        weight = data.get("group_weight")
        if isinstance(weight, (int, float)) and weight:
            return True
    return None


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api_base(canvas) -> str:
    """
    Resolve base URL used by requests_mock in tests.
    DummyCanvas in tests exposes `api_base`; CanvasAPI exposes `base_url` or `api_base`.
    """
    base = getattr(canvas, "api_base", None) or getattr(canvas, "base_url", None)
    if not base:
        raise RuntimeError("Canvas client missing api_base/base_url")
    return base.rstrip("/")


def _full_url(base: str, endpoint: str) -> str:
    # Ensure we hit /api/v1/... even if caller passed "/v1/..."
    if not endpoint.startswith("/api/"):
        endpoint = endpoint if endpoint.startswith("/") else ("/" + endpoint)
        endpoint = "/api" + endpoint
    return f"{base}{endpoint}"


def _normalize_int_map(raw: Optional[Dict[Any, Any]]) -> Dict[int, int]:
    normalized: Dict[int, int] = {}
    for k, v in (raw or {}).items():
        try:
            old_id = int(k)
            new_id = int(v)
        except (TypeError, ValueError):
            continue
        normalized[old_id] = new_id
    return normalized


def _fetch_json(session: requests.Session, base: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = _full_url(base, endpoint)
    resp = session.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data
    return {}


def _resolve_term_id(session: requests.Session, base: str, account_id: int, term_name: str, lg) -> Optional[int]:
    if account_id is None or not term_name:
        return None

    key = (account_id, term_name)
    if key in _TERM_CACHE:
        return _TERM_CACHE[key]

    try:
        data = _fetch_json(
            session,
            base,
            f"/v1/accounts/{account_id}/terms",
            params={"enrollment_term[name]": term_name},
        )
        terms = data.get("enrollment_terms") or data.get("terms") or []
        for term in terms:
            if not isinstance(term, dict):
                continue
            name = term.get("name") or ""
            if name.strip().lower() == term_name.strip().lower():
                term_id = term.get("id")
                if term_id is not None:
                    _TERM_CACHE[key] = int(term_id)
                    return _TERM_CACHE[key]
        lg.warning(
            "Term '%s' not found for account %s; leaving enrollment_term_id unchanged",
            term_name,
            account_id,
        )
    except Exception as exc:
        lg.warning(
            "Failed to resolve term '%s' for account %s: %s",
            term_name,
            account_id,
            exc,
        )
    _TERM_CACHE[key] = None
    return None


def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    target_account_id: Optional[int] = None,
    id_map: Optional[Dict[str, Dict[Any, Any]]] = None,
    auto_set_term: bool = True,
    term_name: str = "Default",
    term_id: Optional[int] = None,
    force_course_dates: bool = True,
    sis_course_id: Optional[str] = None,
    integration_id: Optional[str] = None,
    sis_import_id: Optional[str] = None,
    queue_blueprint_sync: bool = False,
    blueprint_sync_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """
    Import course-level settings and related bits:

      1) PUT /api/v1/courses/:id with fields from course/course_metadata.json (selected keys)
         Also PUT /api/v1/courses/:id/settings if metadata.settings present.

      2) PUT syllabus HTML if course/syllabus.html exists.

      3) Set default_view and front page from course/home.json if present.

      4) Optionally queue Blueprint sync:
         POST /api/v1/courses/:id/blueprint_templates/default/migrations
         with blueprint_sync_options (if any).
    """
    # Per-invocation logger with the actual course id (so logs include it)
    lg = get_logger(artifact="course_settings", course_id=target_course_id)

    base = _api_base(canvas)
    counts = {"updated": 0}
    course_dir = export_root / "course"

    # --- 1) course metadata -> two endpoints
    meta_path = course_dir / "course_metadata.json"
    meta = _read_json(meta_path) if meta_path.exists() else {}

    course_fields: Dict[str, Any] = {}

    if meta:
        # Fields accepted by /courses/:id
        field_map = {
            "name": "name",
            "course_code": "course_code",
            "start_at": "start_at",
            "end_at": "end_at",
            "term_id": "enrollment_term_id",
            "is_blueprint": "is_blueprint_course",
            "default_view": "default_view",
            "time_zone": "time_zone",
            "locale": "locale",
            "is_public": "is_public",
            "public_syllabus": "public_syllabus",
            "apply_assignment_group_weights": "apply_assignment_group_weights",
        }

        for src, dest in field_map.items():
            value = meta.get(src)
            if value is not None:
                course_fields[dest] = value

        for key in (
            "blueprint",
            "blueprint_restrictions",
            "use_blueprint_restrictions_by_object_type",
            "blueprint_restrictions_by_object_type",
        ):
            if meta.get(key) is not None:
                course_fields[key] = meta[key]

        # Rewrite course image using file id_map when available
        files_map = _normalize_int_map((id_map or {}).get("files"))
        image_id = meta.get("image_id") or meta.get("image_id_str")
        try:
            old_image_id = int(image_id) if image_id is not None else None
        except (TypeError, ValueError):
            old_image_id = None

        image_filename = meta.get("course_image_filename") or meta.get("course_image_display_name")

        if old_image_id is not None:
            new_image_id = files_map.get(old_image_id)
            if new_image_id is not None:
                course_fields["image_id"] = new_image_id
                # Clear stale URL so Canvas rebuilds from new image
                course_fields["image_url"] = None
                lg.info(
                    "Remapped course image %s → %s (%s)",
                    old_image_id,
                    new_image_id,
                    image_filename or "unknown filename",
                )
            else:
                lg.warning(
                    "Course image %s (%s) not found in files id_map; leaving image unchanged",
                    old_image_id,
                    image_filename or "unknown filename",
                )

    course_fields["sis_course_id"] = sis_course_id if sis_course_id is not None else ""
    course_fields["integration_id"] = integration_id if integration_id is not None else ""
    course_fields["sis_import_id"] = sis_import_id if sis_import_id is not None else ""

    if "apply_assignment_group_weights" not in course_fields:
        inferred = _detect_weighted_assignment_groups(export_root)
        if inferred is True:
            course_fields["apply_assignment_group_weights"] = True

    # Resolve enrollment term if requested
    resolved_term_id = None
    if auto_set_term:
        resolved_term_id = term_id
        account_id: Optional[int] = target_account_id

        if account_id is None:
            try:
                course_info = _fetch_json(canvas.session, base, f"/v1/courses/{target_course_id}")
                account_id = course_info.get("account_id")  # may be int or str
            except Exception as exc:
                lg.warning("Failed to load target course metadata: %s", exc)

        if account_id is None:
            account_id = meta.get("account_id")

        if resolved_term_id is None and account_id is not None and term_name:
            try:
                resolved_term_id = _resolve_term_id(canvas.session, base, int(account_id), term_name, lg)
            except (TypeError, ValueError):
                lg.warning(
                    "Unable to parse account id %r when resolving term '%s'",
                    account_id,
                    term_name,
                )

        if resolved_term_id is not None:
            course_fields["enrollment_term_id"] = int(resolved_term_id)

    if force_course_dates:
        course_fields["restrict_enrollments_to_course_dates"] = True

    # PUT /courses/:id (hit the mocked URL)
    if course_fields:
        url = _full_url(base, f"/v1/courses/{target_course_id}")
        lg.debug("PUT /courses/%s from course_metadata.json", target_course_id)
        # Canvas expects course-level updates wrapped in {"course": {...}}
        canvas.session.put(url, json={"course": course_fields})
        counts["updated"] += 1

    # PUT /courses/:id/settings if present
    settings = meta.get("settings")
    if isinstance(settings, dict) and settings:
        url = _full_url(base, f"/v1/courses/{target_course_id}/settings")
        lg.debug("PUT /courses/%s/settings", target_course_id)
        canvas.session.put(url, json=settings)
        counts["updated"] += 1

    # --- 2) syllabus HTML
    syllabus_html = course_dir / "syllabus.html"
    if syllabus_html.exists():
        try:
            html = syllabus_html.read_text(encoding="utf-8")
            url = _full_url(base, f"/v1/courses/{target_course_id}")
            lg.debug("PUT syllabus_body via /courses/%s", target_course_id)
            canvas.session.put(url, json={"course": {"syllabus_body": html}})
            lg.info("Syllabus HTML updated")
            counts["updated"] += 1
        except Exception as e:
            lg.warning("Failed to update syllabus HTML: %s", e)

    # --- 3) home page/front page
    home_json = course_dir / "home.json"
    if home_json.exists():
        try:
            hmeta = _read_json(home_json)
            default_view = hmeta.get("default_view")
            front_url = hmeta.get("front_page_url")

            new_slug = None
            if front_url:
                page_slug_map = (id_map or {}).get("pages_url") if isinstance(id_map, dict) else {}
                new_slug = page_slug_map.get(front_url) or front_url
                url = _full_url(base, f"/v1/courses/{target_course_id}/pages/{new_slug}")
                lg.debug("PUT wiki_page front_page=true url=%s (old=%s)", new_slug, front_url)
                try:
                    resp = canvas.session.put(url, json={"wiki_page": {"front_page": True}})
                    resp.raise_for_status()
                    lg.info("Set front page: %s", new_slug)
                    counts["updated"] += 1
                except Exception as e:
                    lg.warning("Failed to set front page %s (slug=%s): %s", front_url, new_slug, e)

            if default_view:
                payload = {"default_view": default_view}
                if default_view == "wiki" and new_slug:
                    payload["home_page_url"] = new_slug
                url = _full_url(base, f"/v1/courses/{target_course_id}")
                lg.debug("PUT course default_view=%s home_page_url=%s", default_view, payload.get("home_page_url"))
                try:
                    resp = canvas.session.put(url, json={"course": payload})
                    resp.raise_for_status()
                    counts["updated"] += 1
                except Exception as e:
                    lg.warning("Failed to set default_view=%s: %s", default_view, e)
        except Exception as e:
            lg.warning("Failed to import home.json: %s", e)

    # --- 4) optional: queue blueprint sync
    if queue_blueprint_sync:
        try:
            url = _full_url(base, f"/v1/courses/{target_course_id}/blueprint_templates/default/migrations")
            payload = blueprint_sync_options or {}
            # Default to copying settings; allow caller to override/extend.
            payload = {"copy_settings": True}
            if blueprint_sync_options:
                payload.update(blueprint_sync_options)
            lg.debug(
                "POST /api/v1/courses/%s/blueprint_templates/default/migrations payload=%s",
                target_course_id, payload
            )
            canvas.session.post(url, json=payload)
        except Exception as e:
            lg.warning("Could not queue Blueprint sync: %s", e)

    lg.info("Course settings import complete")
    return counts
