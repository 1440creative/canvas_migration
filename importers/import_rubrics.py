# importers/import_rubrics.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _find_rubrics_json(export_root: Path) -> Optional[Path]:
    """
    Prefer top-level rubrics/rubrics.json (new),
    fallback to legacy course/rubrics/rubrics.json.
    """
    p1 = Path(export_root) / "rubrics" / "rubrics.json"
    if p1.exists():
        return p1
    p2 = Path(export_root) / "course" / "rubrics" / "rubrics.json"
    if p2.exists():
        return p2
    parent_rubrics = Path(export_root).parent / "rubrics" / "rubrics.json"
    if parent_rubrics.exists():
        return parent_rubrics
    return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _title_key(value: Any) -> Optional[str]:
    if isinstance(value, str):
        key = value.strip()
        if key:
            return key.casefold()
    return None


def _bool_flag(value: Any) -> str:
    return "1" if bool(value) else "0"


def _build_rubric_form_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten rubric dict for Canvas form encoding."""
    payload: Dict[str, Any] = {}

    title = raw.get("title") or "Untitled Rubric"
    payload["rubric[title]"] = title

    if raw.get("points_possible") is not None:
        payload["rubric[points_possible]"] = str(raw["points_possible"])

    if raw.get("free_form_criterion_comments") is not None:
        payload["rubric[free_form_criterion_comments]"] = _bool_flag(raw.get("free_form_criterion_comments"))

    if raw.get("hide_score_total") is not None:
        payload["rubric[hide_score_total]"] = _bool_flag(raw.get("hide_score_total"))

    if raw.get("description"):
        payload["rubric[description]"] = raw["description"]

    criteria = raw.get("criteria") or []
    for idx, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            continue
        prefix = f"rubric[criteria][{idx}]"
        payload[f"{prefix}[id]"] = f"new_{idx}"
        payload[f"{prefix}[description]"] = criterion.get("description") or ""
        if criterion.get("long_description"):
            payload[f"{prefix}[long_description]"] = criterion["long_description"]
        if criterion.get("points") is not None:
            payload[f"{prefix}[points]"] = str(criterion.get("points"))
        payload[f"{prefix}[ignore_for_scoring]"] = _bool_flag(criterion.get("ignore_for_scoring", False))

        ratings = criterion.get("ratings") or []
        if not isinstance(ratings, list) or not ratings:
            ratings = [{"description": "Full Marks", "points": criterion.get("points") or 0}]

        for ridx, rating in enumerate(ratings):
            if not isinstance(rating, dict):
                continue
            rprefix = f"{prefix}[ratings][{ridx}]"
            payload[f"{rprefix}[id]"] = f"new_{idx}_{ridx}"
            payload[f"{rprefix}[description]"] = rating.get("description") or ""
            if rating.get("long_description"):
                payload[f"{rprefix}[long_description]"] = rating["long_description"]
            if rating.get("points") is not None:
                payload[f"{rprefix}[points]"] = str(rating.get("points"))

    return payload


def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]] | None = None,
) -> Dict[str, int]:
    """
    Import rubrics and create rubric associations to mapped objects (assignments).
    Returns counters: {"imported","skipped","failed","total"}.
    """
    log = get_logger(artifact="rubrics_import", course_id=target_course_id)
    id_map = id_map or {}
    assignment_map = id_map.setdefault("assignments", {})
    rubrics_map = id_map.setdefault("rubrics", {})

    normalized_assignments: Dict[int, int] = {}
    for old_key, new_value in assignment_map.items():
        old_norm = _as_int(old_key)
        new_norm = _as_int(new_value)
        if old_norm is not None and new_norm is not None:
            normalized_assignments[old_norm] = new_norm
    if normalized_assignments:
        assignment_map.update(normalized_assignments)

    src_path = _find_rubrics_json(export_root)
    if not src_path:
        log.info("No rubrics to import (missing %s)", (Path(export_root) / "rubrics" / "rubrics.json"))
        return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    log.debug("Loading rubrics from %s", src_path)

    data = _read_json(src_path) or []
    if not isinstance(data, list):
        data = []

    try:
        existing_raw = canvas.get(f"/api/v1/courses/{target_course_id}/rubrics")
    except Exception as exc:
        log.debug("Unable to list existing rubrics: %s", exc)
        existing_raw = []

    existing_by_title: Dict[str, int] = {}
    if isinstance(existing_raw, list):
        for item in existing_raw:
            rid = _as_int(item.get("id") or item.get("rubric_id"))
            key = _title_key(item.get("title") or item.get("title_text") or item.get("rubric_title"))
            if rid is not None and key:
                existing_by_title.setdefault(key, rid)

    imported = 0
    failed = 0
    skipped = 0
    total = 0

    for raw in data:
        if not isinstance(raw, dict):
            skipped += 1
            continue

        total += 1

        title = raw.get("title") or "Untitled Rubric"
        criteria = raw.get("criteria") or []
        payload = _build_rubric_form_payload({**raw, "title": title, "criteria": criteria})

        old_rubric_id = _as_int(raw.get("id"))
        mapped_rubric_id: Optional[int] = None
        if old_rubric_id is not None:
            existing_map = rubrics_map.get(old_rubric_id)
            if existing_map is None:
                existing_map = rubrics_map.get(str(old_rubric_id))
            mapped_rubric_id = _as_int(existing_map)

        title_key = _title_key(title)
        new_rubric_id: Optional[int] = mapped_rubric_id

        if new_rubric_id is None and title_key and title_key in existing_by_title:
            new_rubric_id = existing_by_title[title_key]

        if new_rubric_id is None:
            resp = None
            payload_json: Dict[str, Any] | None = None
            try:
                resp = canvas.post(
                    f"/api/v1/courses/{target_course_id}/rubrics",
                    data=payload,
                )
                payload_json = resp.json() if hasattr(resp, "json") else {}
            except Exception as exc:
                failed += 1
                detail = ""
                response = getattr(exc, "response", None)
                if response is not None and getattr(response, "text", ""):
                    detail = response.text[:500]
                log.error(
                    "failed to create rubric title=%r error=%s detail=%s",
                    title,
                    exc,
                    detail,
                )
                continue

            if isinstance(payload_json, dict):
                candidate = payload_json.get("id") or payload_json.get("rubric_id")
                if candidate is None and isinstance(payload_json.get("data"), dict):
                    candidate = payload_json["data"].get("id")
                new_rubric_id = _as_int(candidate)

            if new_rubric_id is None:
                detail = payload_json if payload_json else getattr(resp, "text", "")
                failed += 1
                log.error("failed to create rubric (no id) title=%r detail=%s", title, detail)
                continue

            imported += 1
            if title_key:
                existing_by_title.setdefault(title_key, new_rubric_id)
        else:
            skipped += 1
            if title_key and new_rubric_id is not None:
                existing_by_title.setdefault(title_key, new_rubric_id)

        if new_rubric_id is None:
            continue

        if old_rubric_id is not None:
            rubrics_map[old_rubric_id] = new_rubric_id

        for assoc in (raw.get("associations") or []):
            if not isinstance(assoc, dict):
                continue
            if (assoc.get("association_type") or "Assignment") != "Assignment":
                continue

            old_assignment_id = _as_int(assoc.get("association_id"))
            if old_assignment_id is None:
                continue

            new_assignment_id = normalized_assignments.get(old_assignment_id)
            if new_assignment_id is None:
                new_assignment_id = _as_int(assignment_map.get(str(old_assignment_id)))
            if new_assignment_id is None:
                new_assignment_id = _as_int(assignment_map.get(old_assignment_id))
            if new_assignment_id is None:
                log.debug(
                    "No assignment mapping for rubric association", extra={
                        "source_assignment_id": old_assignment_id,
                        "rubric_title": title,
                    }
                )
                continue

            assoc_payload = {
                "rubric_association": {
                    "rubric_id": new_rubric_id,
                    "association_type": "Assignment",
                    "association_id": new_assignment_id,
                    "use_for_grading": bool(assoc.get("use_for_grading", True)),
                    "hide_score_total": bool(assoc.get("hide_score_total", False)),
                    "purpose": assoc.get("purpose") or "grading",
                }
            }
            try:
                canvas.post(f"/api/v1/courses/{target_course_id}/rubric_associations", json=assoc_payload)
            except Exception as exc:
                log.warning("rubric association failed title=%r error=%s", title, exc)

    counters = {"imported": imported, "skipped": skipped, "failed": failed, "total": total}
    log.info("Rubrics import complete. imported=%d skipped=%d failed=%d total=%d",
             counters["imported"], counters["skipped"], counters["failed"], counters["total"])
    return counters
