# export_rubrics.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger
from utils.api import DEFAULT_TIMEOUT

__all__ = ["export_rubrics"]

class CanvasLike:
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None):
        ...

DEBUG_EXPORT = os.getenv("EXPORT_RUBRICS_DEBUG") == "1"


def _course_dir(export_root: Path, course_id: int) -> Path:
    export_root = Path(export_root)
    return export_root / "course" / "rubrics"

_LIST_INCLUDE_PARAMS = {
    "include[]": [
        "rubric_associations",
    ]
}

_DETAIL_INCLUDE_PARAMS = {
    "include[]": [
        "rubric_associations",
        "associations",
    ]
}


def _normalize_rubric(obj: Any) -> Dict[str, Any]:
    """Canvas sometimes wraps rubric detail under a 'rubric' key; unwrap it."""
    if isinstance(obj, dict) and isinstance(obj.get("rubric"), dict):
        detail = dict(obj["rubric"])
        # Promote associations present alongside the wrapped object
        for key in ("associations", "rubric_associations"):
            if key in obj and key not in detail:
                detail[key] = obj[key]
        return detail
    return obj if isinstance(obj, dict) else {}


def _fetch_json(canvas: CanvasLike, endpoint: str, *, params: Optional[Dict[str, Any]] = None,
                logger=None) -> Optional[Any]:
    api_root = getattr(canvas, "api_root", "")
    session = getattr(canvas, "session", None)
    if not api_root or session is None:
        return None

    url = f"{api_root.rstrip('/')}{endpoint}"
    try:
        resp = session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        if logger is not None:
            logger.debug(
                "Rubric fetch failed", extra={"endpoint": endpoint, "params": params, "error": str(exc)}
            )
        return None


def _extract_criteria(src: Any) -> List[Dict[str, Any]]:
    crits: List[Dict[str, Any]] = []

    def _coerce_list(val: Any) -> List[Any]:
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            # Some API responses return keyed criteria dict {"_123": {...}}
            return list(val.values())
        return []

    if isinstance(src, dict):
        if isinstance(src.get("criteria"), (list, dict)):
            crits.extend(_coerce_list(src.get("criteria")))
        data = src.get("data")
        if data:
            if isinstance(data, dict) and isinstance(data.get("criteria"), (list, dict)):
                crits.extend(_coerce_list(data.get("criteria")))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if isinstance(item.get("criteria"), (list, dict)):
                            crits.extend(_coerce_list(item.get("criteria")))
                        elif isinstance(item.get("criterion"), dict):
                            crits.append(item.get("criterion"))
                        else:
                            # Item itself looks like a criterion (Canvas data array)
                            crits.append(item)
    return [c for c in crits if isinstance(c, dict)]


def _slim_rubric(r: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce Canvas rubric to the minimal structure our importer/tests need."""
    out: Dict[str, Any] = {
        "id": r.get("id"),
        "title": r.get("title"),
        "points_possible": r.get("points_possible"),  # <-- required by test
        "free_form_criterion_comments": bool(r.get("free_form_criterion_comments", False)),
        "criteria": [],
        "associations": [],
    }

    # criteria
    seen_criteria = set()
    for c in _extract_criteria(r):
        cid = c.get("id") or c.get("criterion_id")
        marker = cid if cid is not None else (c.get("description"), c.get("long_description"))
        if marker in seen_criteria:
            continue
        seen_criteria.add(marker)
        raw_ratings = c.get("ratings")
        if isinstance(raw_ratings, dict):
            ratings_iter = raw_ratings.values()
        elif isinstance(raw_ratings, list):
            ratings_iter = raw_ratings
        else:
            ratings_iter = []

        out["criteria"].append({
            "description": c.get("description"),
            "long_description": c.get("long_description"),
            "points": c.get("points"),
            "ignore_for_scoring": bool(c.get("ignore_for_scoring", False)),
            "ratings": [
                {"description": rt.get("description"), "points": rt.get("points")}
                for rt in ratings_iter
                if isinstance(rt, dict)
            ],
        })

    # associations (only the assignment mapping details we need later)
    for a in (r.get("associations") or []):
        out["associations"].append({
            "association_type": a.get("association_type"),
            "association_id": a.get("association_id"),
            "use_for_grading": bool(a.get("use_for_grading", True)),
            "purpose": a.get("purpose") or "grading",
            "hide_score_total": bool(a.get("hide_score_total", False)),
            "hide_points": bool(a.get("hide_points", False)),
        })

    return out

def export_rubrics(course_id: int, export_root: Path, canvas: CanvasLike) -> List[Dict[str, Any]]:
    """
    Export rubrics with associations (slim form) and write:
      - per-rubric JSON under course/<id>/rubrics/<rubric_id>.json
      - course/<id>/rubrics/index.json (metadata index if you already rely on it)
      - rubrics/rubrics.json (consolidated slim list used by tests/importer)
    """
    log = get_logger(artifact="rubrics_export", course_id=course_id)

    # Fetch rubrics with associations
    raw = canvas.get(
        f"/api/v1/courses/{course_id}/rubrics",
        params=_LIST_INCLUDE_PARAMS.copy(),
    )
    rubrics: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            base = _normalize_rubric(item)
            rid = base.get("id")
            if rid is None:
                continue
            detail_norm: Dict[str, Any] = {}

            for endpoint, params in [
                (f"/courses/{course_id}/rubrics/{rid}", _DETAIL_INCLUDE_PARAMS.copy()),
                (f"/courses/{course_id}/rubrics/{rid}", None),
                (f"/rubrics/{rid}", _DETAIL_INCLUDE_PARAMS.copy()),
                (f"/rubrics/{rid}", None),
            ]:
                detail_data = _fetch_json(canvas, endpoint, params=params, logger=log)
                if detail_data:
                    detail_norm = _normalize_rubric(detail_data)
                    if detail_norm:
                        break

            if not detail_norm:
                log.warning(
                    "Falling back to list metadata for rubric", extra={"rubric_id": rid}
                )

            merged = {**base, **detail_norm}
            if DEBUG_EXPORT:
                debug_dir = Path(export_root) / "rubrics_raw"
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"rubric_{rid}.json").write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

            rubrics.append(merged)

    # Slim them down
    slim: List[Dict[str, Any]] = [_slim_rubric(r) for r in rubrics]

    for entry in slim:
        entry.setdefault("course_id", course_id)
        associations = entry.get("associations") or []
        for assoc in associations:
            if isinstance(assoc, dict):
                assoc.setdefault("course_id", course_id)

    # Preserve existing per-rubric layout (under course/<id>/rubrics)
    course_dir = _course_dir(export_root, course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    for r in slim:
        rid = r.get("id")
        if rid is not None:
            (course_dir / f"rubric_{rid}.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    # optional index (kept for compatibility)
    (course_dir / "index.json").write_text(
        json.dumps([{"id": r.get("id"), "title": r.get("title")} for r in slim], indent=2) + "\n",
        encoding="utf-8"
    )

    # Consolidated slim list where tests look
    top_rubrics_dir = Path(export_root) / "rubrics"
    top_rubrics_dir.mkdir(parents=True, exist_ok=True)
    (top_rubrics_dir / "rubrics.json").write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")

    log.info("Exported %d rubrics", len(slim))
    return slim
