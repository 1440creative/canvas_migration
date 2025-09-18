# importers/import_rubrics.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger


def _pick_rubrics_dir(export_root: Path) -> Optional[Path]:
    """Prefer <course>/rubrics, but fall back to legacy ../rubrics if present."""
    rubrics_dir = export_root / "rubrics"
    if rubrics_dir.exists():
        return rubrics_dir
    # backward-compat: if export_root looks like .../<course_id>, check parent/rubrics
    if export_root.name.isdigit():
        legacy = export_root.parent / "rubrics"
        if legacy.exists():
            return legacy
    return None


def _coerce_criteria(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Best-effort extraction of Canvas rubric criteria structure from the exported object.
    Accepts a variety of shapes (top-level 'criteria', nested under 'data'/'rubric', etc.).
    """
    candidates = [
        payload.get("criteria"),
        payload.get("data", {}).get("criteria") if isinstance(payload.get("data"), dict) else None,
        payload.get("rubric", {}).get("criteria") if isinstance(payload.get("rubric"), dict) else None,
    ]
    for c in candidates:
        if isinstance(c, list):
            return c

    # Some tenants return 'data' as a list of criteria directly
    if isinstance(payload.get("data"), list):
        return payload["data"]

    return []


def _extract_title(payload: Dict[str, Any]) -> str:
    for k in ("title", "name", "rubric_title"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # try nested
    rub = payload.get("rubric") or payload.get("data") or {}
    if isinstance(rub, dict):
        for k in ("title", "name"):
            v = rub.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return "Imported Rubric"


def _extract_points_possible(payload: Dict[str, Any]) -> Optional[float]:
    for k in ("points_possible", "total_points"):
        v = payload.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    rub = payload.get("rubric")
    if isinstance(rub, dict):
        for k in ("points_possible", "total_points"):
            v = rub.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[int, int]],
) -> None:
    """
    Create rubrics in the TARGET course from exported rubric JSON files.

    - Reads: <export_root>/rubrics/rubric_<id>.json
    - Writes: id_map["rubrics"][old_id] = new_id
    """
    log = get_logger(artifact="rubrics_import", course_id=target_course_id)

    rubrics_dir = _pick_rubrics_dir(export_root)
    if not rubrics_dir:
        log.info("No rubrics directory found (nothing to import).")
        return

    files = sorted(rubrics_dir.glob("rubric_*.json"))
    if not files:
        log.info("Rubrics directory is empty (nothing to import).")
        return

    rmap: Dict[int, int] = id_map.setdefault("rubrics", {})
    created = 0
    failed = 0

    for jf in files:
        try:
            blob = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            failed += 1
            log.warning("Skipping unreadable rubric file %s: %s", jf, e)
            continue

        raw = blob.get("rubric") if isinstance(blob, dict) else blob
        if not isinstance(raw, dict):
            failed += 1
            log.warning("Malformed rubric json in %s (expected object)", jf)
            continue

        old_id = raw.get("id")
        title = _extract_title(raw)
        criteria = _coerce_criteria(raw)
        points_possible = _extract_points_possible(raw)

        payload: Dict[str, Any] = {
            "rubric": {
                "title": title,
                # Canvas will recalc from criteria if omitted; pass when we have it
                **({"points_possible": points_possible} if points_possible is not None else {}),
                # Allow free-form comments if the source had it; default False otherwise
                "free_form_criterion_comments": bool(
                    raw.get("free_form_criterion_comments")
                    or (raw.get("rubric") or {}).get("free_form_criterion_comments")
                ),
                "criteria": criteria or [],
            },
            # Optional: immediately associate to the course (non-grading association)
            "rubric_association": {
                "association_type": "Course",
                "association_id": target_course_id,
                "use_for_grading": False,
            },
        }

        try:
            # POST returns the created rubric JSON (or the association). Use your wrapper.
            res = canvas.post_json(f"/api/v1/courses/{target_course_id}/rubrics", payload=payload)
            new_id = (
                (res.get("id") if isinstance(res, dict) else None)
                or (res.get("rubric", {}).get("id") if isinstance(res, dict) else None)
            )
            if not isinstance(new_id, int):
                raise RuntimeError(f"Create rubric returned no id; response keys={list(res) if isinstance(res, dict) else type(res)}")

            if isinstance(old_id, int):
                rmap[old_id] = int(new_id)

            created += 1
            log.info("Created rubric '%s' → new_id=%s", title, new_id)
        except Exception as e:
            failed += 1
            log.exception("Failed to create rubric from %s: %s", jf.name, e)

    log.info("Rubrics import complete. created=%d failed=%d total=%d", created, failed, created + failed)
