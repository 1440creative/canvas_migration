from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import requests
from logging_setup import get_logger
from importers.import_files import _upload_one

# Safe module-level logger (no course id at import time)
log = get_logger(artifact="course_settings", course_id="-")


_TERM_CACHE: Dict[Tuple[int, str], Optional[int]] = {}

DEFAULT_NAVIGATION: List[Dict[str, Any]] = [
    {"id": "home", "hidden": False},
    {"id": "modules", "hidden": False},
    {"id": "assignments", "hidden": False},
    {"id": "quizzes", "hidden": False},
    {"id": "discussions", "hidden": False},
    {"id": "announcements", "hidden": False},
    {"id": "grades", "hidden": False},
    {"id": "people", "hidden": False},
    {"id": "pages", "hidden": True},
    {"id": "files", "hidden": True},
    {"id": "syllabus", "hidden": True},
    {"id": "outcomes", "hidden": True},
    {"id": "collaborations", "hidden": True},
    {"id": "conferences", "hidden": True},
    {"id": "attendance", "hidden": True},
    {"id": "settings", "hidden": False},
]
_NAV_PROTECTED_IDS = {"settings"}


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


def _reapply_assignment_group_weights(
    *,
    export_root: Path,
    canvas,
    target_course_id: int,
    id_map: Dict[str, Dict[Any, Any]],
    log,
) -> None:
    groups_dir = export_root / "assignment_groups"
    if not groups_dir.exists():
        return

    mapping_raw = id_map.get("assignment_groups") if isinstance(id_map, dict) else {}
    if not isinstance(mapping_raw, dict):
        mapping_raw = {}

    api_root = _api_base(canvas)

    for meta_path in sorted(groups_dir.rglob("assignment_group_metadata.json")):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        old_id = data.get("id")
        if old_id is None:
            continue
        new_id = mapping_raw.get(old_id) or mapping_raw.get(str(old_id))
        if new_id is None:
            continue

        weight = data.get("group_weight")
        if weight is None:
            continue

        try:
            new_id_int = int(new_id)
        except (TypeError, ValueError):
            continue

        payload = {"assignment_group": {"group_weight": weight}}
        if data.get("name"):
            payload["assignment_group"]["name"] = data["name"]

        url = _full_url(api_root, f"/v1/courses/{target_course_id}/assignment_groups/{new_id_int}")
        response = None
        try:
            response = canvas.session.put(url, json=payload)
            response.raise_for_status()
        except Exception as exc:
            log.warning(
                "Failed to reapply group weight",
                extra={
                    "old_id": old_id,
                    "new_id": new_id_int,
                    "group_weight": weight,
                    "status": getattr(response, "status_code", None),
                    "error": str(exc),
                },
            )
            continue

        log.debug(
            "Reapplied assignment group weight",
            extra={
                "old_id": old_id,
                "new_id": new_id_int,
                "group_weight": weight,
            },
        )


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _read_json_list(p: Path) -> list:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


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

def _load_navigation_spec(course_dir: Path, lg) -> List[Dict[str, Any]]:
    nav_path = course_dir / "course_navigation.json"
    nav_items = _read_json_list(nav_path) if nav_path.exists() else []
    if nav_items:
        return [item for item in nav_items if isinstance(item, dict) and item.get("id")]
    lg.debug("course_navigation.json missing; using default navigation template")
    return [dict(item) for item in DEFAULT_NAVIGATION]


def _resolve_course_image_file(course_dir: Path, meta: Dict[str, Any]) -> Optional[Path]:
    """
    Find the exported course image file if present.
    """
    candidates: List[str] = []
    rel_path = meta.get("course_image_export_path")
    if isinstance(rel_path, str) and rel_path.strip():
        candidates.append(rel_path.strip())

    for key in ("course_image_filename", "course_image_display_name"):
        name = meta.get(key)
        if isinstance(name, str) and name.strip():
            candidates.append(name.strip())

    seen: set[str] = set()
    for name in candidates:
        safe_name = Path(name).name
        if not safe_name or safe_name in seen:
            continue
        seen.add(safe_name)
        candidate = course_dir / safe_name
        if candidate.exists():
            return candidate
    return None


def _upload_course_image(
    *,
    canvas,
    target_course_id: int,
    file_path: Path,
    logger,
) -> int:
    """
    Upload the course card image file and return the new Canvas file id.
    """
    folder_path = f"{target_course_id}/course_image"
    new_id = _upload_one(
        canvas=canvas,
        course_id=target_course_id,
        file_path=file_path,
        folder_path=folder_path,
        on_duplicate="overwrite",
        logger=logger,
    )
    return int(new_id)


def _create_course_grading_standard(
    *,
    canvas,
    base: str,
    target_course_id: int,
    standard: Dict[str, Any],
    log,
) -> int:
    title = standard.get("title") or standard.get("name") or "Imported grading scheme"
    entries_raw = standard.get("grading_scheme")
    entries: List[Dict[str, Any]] = []
    if isinstance(entries_raw, list):
        for entry in entries_raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            value = entry.get("value")
            if not isinstance(name, str):
                continue
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                continue
            entries.append({"name": name, "value": value_f})

    if not entries:
        raise ValueError("grading scheme entries missing")

    payload = {
        "grading_standard": {
            "title": title,
            "grading_scheme": entries,
        }
    }

    url = _full_url(base, f"/v1/courses/{target_course_id}/grading_standards")
    response = canvas.session.post(url, json=payload)
    response.raise_for_status()
    try:
        data = response.json()
    except Exception:
        data = {}

    candidates = []
    if isinstance(data, dict):
        candidates.extend([
            data.get("id"),
            data.get("grading_standard_id"),
            data.get("grading_standard", {}).get("id") if isinstance(data.get("grading_standard"), dict) else None,
        ])

    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue

    raise RuntimeError("Canvas grading standard creation did not return an id")


def _apply_course_navigation(
    *,
    session: requests.Session,
    base: str,
    target_course_id: int,
    nav_items: List[Dict[str, Any]],
    log,
    counts: Dict[str, int],
) -> None:
    ordered: List[Dict[str, Any]] = []
    for item in nav_items:
        if not isinstance(item, dict):
            continue
        tab_id = item.get("id")
        if not tab_id:
            continue
        tab_id_str = str(tab_id)
        hidden = item.get("hidden")
        position = item.get("position")
        can_add = item.get("can_add_to_nav")
        has_permission = item.get("has_permission")

        if has_permission is False:
            log.debug("Skipping navigation tab %s (no permission)", tab_id_str)
            continue
        if can_add is False:
            log.debug("Skipping navigation tab %s (cannot add to nav)", tab_id_str)
            continue

        ordered.append(
            {
                "id": tab_id_str,
                "hidden": hidden,
                "position": position,
            }
        )

    if not ordered:
        log.debug("No navigation entries to apply")
        return

    # Preserve incoming order; fall back to exported positions if they are numeric
    ordered.sort(key=lambda entry: (
        0 if isinstance(entry.get("position"), (int, float)) else 1,
        entry.get("position") or 0,
    ))

    for idx, entry in enumerate(ordered, start=1):
        tab_id = entry["id"]
        if tab_id in _NAV_PROTECTED_IDS:
            log.debug("Skipping protected navigation tab %s", tab_id)
            continue
        payload: Dict[str, Any] = {"position": idx}
        hidden_val = entry.get("hidden")
        if hidden_val is not None:
            payload["hidden"] = bool(hidden_val)

        url = _full_url(base, f"/v1/courses/{target_course_id}/tabs/{tab_id}")
        response = None
        try:
            response = session.put(url, json=payload)
            response.raise_for_status()
            counts["updated"] += 1
            log.debug(
                "Updated navigation tab %s", tab_id,
                extra={"position": idx, "hidden": payload.get("hidden")},
            )
        except Exception as exc:
            log.warning(
                "Failed to update navigation tab %s",
                tab_id,
                extra={
                    "position": idx,
                    "hidden": payload.get("hidden"),
                    "status": getattr(response, "status_code", None),
                    "error": str(exc),
                },
            )

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
    term_name: str = "Default Term",
    term_id: Optional[int] = None,
    participation_mode: str = "course",
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

    participation_mode_normalized = (participation_mode or "course").strip().lower()
    if participation_mode_normalized not in {"course", "term", "inherit"}:
        raise ValueError(f"Unsupported participation_mode: {participation_mode}")

    # --- 1) course metadata -> two endpoints
    meta_path = course_dir / "course_metadata.json"
    meta = _read_json(meta_path) if meta_path.exists() else {}

    course_fields: Dict[str, Any] = {}
    settings_data: Optional[Dict[str, Any]] = None

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

        settings_data = meta.get("settings") if isinstance(meta.get("settings"), dict) else None

        def _ensure_settings_dict() -> Dict[str, Any]:
            nonlocal settings_data
            if settings_data is None:
                settings_data = {}
            return settings_data

        def _set_setting_flag(key: str, value: Any) -> None:
            data = _ensure_settings_dict()
            data[key] = value

        grading_standard_enabled_raw = meta.get("grading_standard_enabled")
        if grading_standard_enabled_raw is None and settings_data is not None:
            grading_standard_enabled_raw = settings_data.get("grading_standard_enabled")
        grading_standard_enabled = bool(grading_standard_enabled_raw)

        old_grading_standard_id = meta.get("grading_standard_id")
        if old_grading_standard_id is None and settings_data is not None:
            old_grading_standard_id = settings_data.get("grading_standard_id")

        old_grading_standard_id_int: Optional[int]
        try:
            old_grading_standard_id_int = int(old_grading_standard_id) if old_grading_standard_id is not None else None
        except (TypeError, ValueError):
            old_grading_standard_id_int = None

        grading_standard_spec = meta.get("grading_standard") if isinstance(meta.get("grading_standard"), dict) else None

        new_grading_standard_id: Optional[int] = None
        if grading_standard_enabled:
            grading_map = _normalize_int_map((id_map or {}).get("grading_standards"))
            if old_grading_standard_id_int is not None:
                new_grading_standard_id = grading_map.get(old_grading_standard_id_int)

            if new_grading_standard_id is None and grading_standard_spec is not None:
                try:
                    new_grading_standard_id = _create_course_grading_standard(
                        canvas=canvas,
                        base=base,
                        target_course_id=target_course_id,
                        standard=grading_standard_spec,
                        log=lg,
                    )
                    lg.info(
                        "Created course grading standard %s",
                        grading_standard_spec.get("title") or grading_standard_spec.get("name"),
                    )
                    if isinstance(id_map, dict) and old_grading_standard_id_int is not None:
                        bucket = id_map.setdefault("grading_standards", {})
                        bucket[str(old_grading_standard_id_int)] = new_grading_standard_id
                except Exception as exc:
                    lg.warning(
                        "Failed to create grading standard %s: %s",
                        grading_standard_spec.get("title") or grading_standard_spec.get("name") or old_grading_standard_id,
                        exc,
                    )

            if new_grading_standard_id is not None:
                course_fields["grading_standard_id"] = int(new_grading_standard_id)
                course_fields["grading_standard_enabled"] = True
                if settings_data is not None:
                    settings_data["grading_standard_id"] = int(new_grading_standard_id)
                    settings_data["grading_standard_enabled"] = True
                meta["grading_standard_id"] = int(new_grading_standard_id)
                meta["grading_standard_enabled"] = True
            elif grading_standard_enabled:
                lg.warning(
                    "Grading standard %s could not be mapped or created; course will use default scheme",
                    old_grading_standard_id,
                )
                course_fields.pop("grading_standard_id", None)
                course_fields["grading_standard_enabled"] = False
                settings_dict = _ensure_settings_dict()
                settings_dict.pop("grading_standard_id", None)
                settings_dict["grading_standard_enabled"] = False
                meta["grading_standard_id"] = None
                meta["grading_standard_enabled"] = False

        # Rewrite course image using file id_map when available, otherwise fall back to uploaded export file
        files_map = _normalize_int_map((id_map or {}).get("files"))
        image_id = meta.get("image_id") or meta.get("image_id_str")
        if image_id is None and settings_data:
            image_id = settings_data.get("image_id") or settings_data.get("image_id_str") or settings_data.get("banner_image_id")
        try:
            old_image_id = int(image_id) if image_id is not None else None
        except (TypeError, ValueError):
            old_image_id = None

        image_filename = meta.get("course_image_filename") or meta.get("course_image_display_name")
        image_file = _resolve_course_image_file(course_dir, meta)

        def _record_file_mapping(old_id: Optional[int], new_id: int) -> None:
            if old_id is None:
                return
            if isinstance(id_map, dict):
                bucket = id_map.setdefault("files", {})
                bucket[int(old_id)] = int(new_id)

        if old_image_id is not None:
            new_image_id = files_map.get(old_image_id)
            if new_image_id is not None:
                course_fields["image_id"] = new_image_id
                course_fields["image_url"] = None
                lg.info(
                    "Remapped course image %s → %s (%s)",
                    old_image_id,
                    new_image_id,
                    image_filename or "unknown filename",
                )
            elif image_file is not None:
                try:
                    uploaded_id = _upload_course_image(
                        canvas=canvas,
                        target_course_id=target_course_id,
                        file_path=image_file,
                        logger=lg,
                    )
                except Exception as exc:
                    lg.warning(
                        "Failed to upload course image %s (%s): %s",
                        image_file.name,
                        image_filename or "unknown filename",
                        exc,
                    )
                else:
                    course_fields["image_id"] = uploaded_id
                    course_fields["image_url"] = None
                    _record_file_mapping(old_image_id, uploaded_id)
                    lg.info(
                        "Uploaded course image fallback for %s (%s) → %s",
                        old_image_id,
                        image_file.name,
                        uploaded_id,
                    )
            else:
                lg.warning(
                    "Course image %s (%s) not found in files id_map and no exported image file present; leaving image unchanged",
                    old_image_id,
                    image_filename or "unknown filename",
                )
        elif image_file is not None:
            try:
                uploaded_id = _upload_course_image(
                    canvas=canvas,
                    target_course_id=target_course_id,
                    file_path=image_file,
                    logger=lg,
                )
            except Exception as exc:
                lg.warning(
                    "Failed to upload course image file %s: %s",
                    image_file.name,
                    exc,
                )
            else:
                course_fields["image_id"] = uploaded_id
                course_fields["image_url"] = None
                lg.info("Uploaded course image %s → %s", image_file.name, uploaded_id)

        meta_restrict = meta.get("restrict_enrollments_to_course_dates")
        if meta_restrict is None and settings_data is not None:
            meta_restrict = settings_data.get("restrict_enrollments_to_course_dates")

        original_future = settings_data.get("restrict_student_future_view") if settings_data else None
        original_past = settings_data.get("restrict_student_past_view") if settings_data else None
        if original_future is None:
            original_future = meta.get("restrict_student_future_view")
        if original_past is None:
            original_past = meta.get("restrict_student_past_view")

        if participation_mode_normalized == "course":
            course_fields["restrict_enrollments_to_course_dates"] = True
            _set_setting_flag("restrict_enrollments_to_course_dates", True)
            _set_setting_flag(
                "restrict_student_future_view",
                bool(original_future) if original_future is not None else True,
            )
            _set_setting_flag(
                "restrict_student_past_view",
                bool(original_past) if original_past is not None else True,
            )
        elif participation_mode_normalized == "term":
            course_fields["restrict_enrollments_to_course_dates"] = False
            _set_setting_flag("restrict_enrollments_to_course_dates", False)
            _set_setting_flag("restrict_student_future_view", False)
            _set_setting_flag("restrict_student_past_view", False)
        else:  # inherit
            if meta_restrict is not None:
                restrict_val = bool(meta_restrict)
                course_fields["restrict_enrollments_to_course_dates"] = restrict_val
                _set_setting_flag("restrict_enrollments_to_course_dates", restrict_val)
            if original_future is not None:
                _set_setting_flag("restrict_student_future_view", bool(original_future))
            if original_past is not None:
                _set_setting_flag("restrict_student_past_view", bool(original_past))

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

    # PUT /courses/:id (hit the mocked URL)
    if course_fields:
        url = _full_url(base, f"/v1/courses/{target_course_id}")
        lg.debug("PUT /courses/%s from course_metadata.json", target_course_id)
        response = None
        try:
            # Canvas expects course-level updates wrapped in {"course": {...}}
            response = canvas.session.put(url, json={"course": course_fields})
            response.raise_for_status()
        except Exception as exc:
            extra: Dict[str, Any] = {
                "status": getattr(response, "status_code", None),
                "error": str(exc),
            }
            if response is not None:
                try:
                    extra["response"] = response.text
                except Exception:
                    pass
            lg.warning("Failed to update course metadata", extra=extra)

            fallback_keys = {
                "restrict_enrollments_to_course_dates",
                "grading_standard_id",
                "grading_standard_enabled",
                "image_id",
                "image_url",
                "apply_assignment_group_weights",
                "sis_course_id",
                "integration_id",
                "sis_import_id",
            }
            fallback_payload: Dict[str, Any] = {}
            for key in fallback_keys:
                if key not in course_fields:
                    continue
                value = course_fields[key]
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                fallback_payload[key] = value
            if fallback_payload:
                fallback_response = None
                try:
                    fallback_response = canvas.session.put(url, json={"course": fallback_payload})
                    fallback_response.raise_for_status()
                except Exception as fallback_exc:
                    fallback_extra: Dict[str, Any] = {
                        "status": getattr(fallback_response, "status_code", None),
                        "error": str(fallback_exc),
                        "fields": sorted(fallback_payload.keys()),
                    }
                    if fallback_response is not None:
                        try:
                            fallback_extra["response"] = fallback_response.text
                        except Exception:
                            pass
                    lg.warning(
                        "Fallback course metadata update failed (fields=%s)",
                        ",".join(sorted(fallback_payload.keys())) or "none",
                        extra=fallback_extra,
                    )
                else:
                    counts["updated"] += 1
                    lg.info(
                        "Applied fallback course metadata update fields=%s",
                        ",".join(sorted(fallback_payload.keys())) or "none",
                    )
        else:
            counts["updated"] += 1

    # PUT /courses/:id/settings if present
    settings = settings_data if isinstance(settings_data, dict) else None
    if isinstance(settings, dict) and settings:
        url = _full_url(base, f"/v1/courses/{target_course_id}/settings")
        lg.debug("PUT /courses/%s/settings", target_course_id)
        response = None
        try:
            response = canvas.session.put(url, json=settings)
            response.raise_for_status()
        except Exception as exc:
            lg.warning(
                "Failed to update course settings",
                extra={
                    "status": getattr(response, "status_code", None),
                    "error": str(exc),
                },
            )
        else:
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

    # --- 3b) course navigation ordering + visibility
    try:
        nav_items = _load_navigation_spec(course_dir, lg)
        _apply_course_navigation(
            session=canvas.session,
            base=base,
            target_course_id=target_course_id,
            nav_items=nav_items,
            log=lg,
            counts=counts,
        )
    except Exception as exc:
        lg.warning("Failed to apply course navigation settings: %s", exc)

    if course_fields.get("apply_assignment_group_weights") or _detect_weighted_assignment_groups(export_root):
        try:
            _reapply_assignment_group_weights(
                export_root=export_root,
                canvas=canvas,
                target_course_id=target_course_id,
                id_map=id_map or {},
                log=lg,
            )
        except Exception as exc:
            lg.warning("Failed to reapply assignment group weights: %s", exc)

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
