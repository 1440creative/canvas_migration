# importers/import_rubrics.py
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from logging_setup import get_logger
from utils.api import DEFAULT_TIMEOUT


__all__ = ["import_rubrics"]


class CanvasLikeProtocol:
    api_root: str
    session: requests.Session
    def get(self, endpoint: str, **kwargs) -> Any: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _normalize_criteria(raw: Any) -> List[dict]:
    """
    Accept a few shapes and normalize to Canvas rubric criteria list:
    Each criterion: {description, long_description, points, ratings:[{description,points}]}
    """
    if not isinstance(raw, list):
        return []
    out: List[dict] = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            continue
        desc = c.get("description") or c.get("title") or f"Criterion {i+1}"
        long_desc = c.get("long_description") or c.get("longDescription") or ""
        try:
            points = float(c.get("points")) if c.get("points") is not None else None
        except Exception:
            points = None

        ratings = []
        raw_ratings = c.get("ratings") or []
        if isinstance(raw_ratings, list) and raw_ratings:
            for r in raw_ratings:
                if not isinstance(r, dict):
                    continue
                r_desc = r.get("description") or r.get("title") or ""
                try:
                    r_pts = float(r.get("points")) if r.get("points") is not None else None
                except Exception:
                    r_pts = None
                if r_pts is None:
                    continue
                ratings.append({"description": r_desc, "points": r_pts})

        # Guarantee at least one rating
        if not ratings:
            # If total points is missing, default to 0..1
            base_pts = 1.0 if points is None else points
            ratings = [{"description": "Full Marks", "points": base_pts}]

        # If 'points' is missing at the criterion level, set it to max rating
        if points is None:
            points = max((r["points"] for r in ratings), default=1.0)

        out.append(
            {
                "description": str(desc),
                "long_description": str(long_desc or ""),
                "points": float(points),
                "ratings": ratings,
            }
        )
    return out


def _form_payload_from_rubric(
    *,
    rubric: dict,
    course_id: int,
) -> Dict[str, str]:
    """
    Canvas' rubrics create endpoint is happiest with form-encoded bracketed keys.
    This builds a payload like:
      rubric[title], rubric[free_form_criterion_comments]
      rubric[criteria][0][description], [long_description], [points]
      rubric[criteria][0][ratings][0][description], [points]
      rubric_association[association_type], [association_id], [use_for_grading], [purpose]
    """
    title = rubric.get("title") or rubric.get("name") or "Imported Rubric"
    free_form = _as_bool(rubric.get("free_form_criterion_comments"), False)
    criteria = _normalize_criteria(rubric.get("criteria") or rubric.get("data") or [])

    form: Dict[str, str] = {
        "rubric[title]": str(title),
        "rubric[free_form_criterion_comments]": "1" if free_form else "0",
        # Create it as a course-level rubric (bookmark). Instructors can attach later.
        "rubric_association[association_type]": "Course",
        "rubric_association[association_id]": str(course_id),
        "rubric_association[use_for_grading]": "0",
        "rubric_association[purpose]": "bookmark",
    }

    for i, c in enumerate(criteria):
        prefix = f"rubric[criteria][{i}]"
        form[f"{prefix}[description]"] = c["description"]
        form[f"{prefix}[long_description]"] = c.get("long_description", "") or ""
        form[f"{prefix}[points]"] = str(c["points"])
        # Optional: set a local id so Canvas doesn't choke on repeats
        form[f"{prefix}[id]"] = f"crit_{i+1}"
        # Ratings
        for j, r in enumerate(c.get("ratings", []) or []):
            rkey = f"{prefix}[ratings][{j}]"
            form[f"{rkey}[description]"] = r.get("description", "") or ""
            form[f"{rkey}[points]"] = str(r["points"])

    return form


def _json_payload_from_rubric(*, rubric: dict, course_id: int) -> Dict[str, Any]:
    title = rubric.get("title") or rubric.get("name") or "Imported Rubric"
    free_form = _as_bool(rubric.get("free_form_criterion_comments"), False)
    criteria = _normalize_criteria(rubric.get("criteria") or rubric.get("data") or [])
    return {
        "rubric": {
            "title": title,
            "free_form_criterion_comments": free_form,
            "criteria": criteria,
        },
        "rubric_association": {
            "association_type": "Course",
            "association_id": int(course_id),
            "use_for_grading": False,
            "purpose": "bookmark",
        },
    }


def _list_existing_titles(canvas: CanvasLikeProtocol, course_id: int) -> set[str]:
    titles: set[str] = set()
    try:
        rubs = canvas.get(f"/api/v1/courses/{course_id}/rubrics")
        if isinstance(rubs, list):
            for r in rubs:
                t = r.get("title") or r.get("name")
                if t:
                    titles.add(str(t))
    except Exception:
        pass
    return titles


def import_rubrics(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLikeProtocol,
    verbosity: int = 1,
) -> None:
    """
    Import rubrics from export_root/<course_id>/rubrics/*.json
    Creates course-level (bookmark) rubrics in the target course.
    """
    log = get_logger(artifact="rubrics_import", course_id=target_course_id)

    # Find the course folder under export_root:
    # - If export_root is .../<course_id>, use it
    # - Else, if there is a single numeric child, use that
    course_dir = export_root
    if not (export_root / "rubrics").exists():
        # try nested structure export_root/<id>/
        try:
            subdirs = [d for d in export_root.iterdir() if d.is_dir() and re.match(r"^\d+$", d.name)]
            if len(subdirs) == 1:
                course_dir = subdirs[0]
        except Exception:
            pass

    rubrics_dir = course_dir / "rubrics"
    if not rubrics_dir.exists():
        log.info("No rubrics directory at %s (nothing to import)", rubrics_dir)
        return

    files = sorted(rubrics_dir.glob("rubric_*.json"))
    if not files:
        log.info("No rubric_*.json files in %s (nothing to import)", rubrics_dir)
        return

    existing_titles = _list_existing_titles(canvas, target_course_id)

    created = 0
    failed = 0

    for jf in files:
        data = _read_json(jf)
        if not data:
            log.warning("Skipping unreadable rubric file: %s", jf)
            continue

        # Typical export stored the raw Canvas rubric under "rubric" or "data"
        rubric = data.get("rubric") if isinstance(data.get("rubric"), dict) else data
        title = rubric.get("title") or rubric.get("name") or jf.stem

        if title in existing_titles:
            log.info("Rubric with title %r already exists; skipping", title)
            continue

        # 1) Try form-encoded (Canvas’ preferred shape for this endpoint)
        form = _form_payload_from_rubric(rubric=rubric, course_id=target_course_id)
        url = f"{canvas.api_root.rstrip('/')}/courses/{target_course_id}/rubrics"

        headers = canvas.session.headers.copy()
        # IMPORTANT: do NOT send JSON content type for form data
        headers.pop("Content-Type", None)

        try:
            resp = canvas.session.post(url, data=form, headers=headers, timeout=DEFAULT_TIMEOUT)
            if resp.status_code >= 400:
                body = resp.text[:600]
                log.warning("Rubric create (form) error status=%s body=%r", resp.status_code, body)
            resp.raise_for_status()
            created += 1
            existing_titles.add(title)
            log.info("Created rubric (form): %s", title)
            continue
        except requests.HTTPError:
            # Fall through to JSON attempt below after logging
            pass
        except Exception as e:
            log.exception("Rubric form submit failed for %s: %s", title, e)

        # 2) Fallback to JSON
        try:
            payload = _json_payload_from_rubric(rubric=rubric, course_id=target_course_id)
            res = canvas.post_json(f"/api/v1/courses/{target_course_id}/rubrics", payload=payload)
            # if we got a dict back, assume success
            created += 1
            existing_titles.add(title)
            log.info("Created rubric (json): %s", title)
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            body = (e.response.text[:600] if getattr(e, "response", None) is not None else "")
            log.error("Failed to create rubric from %s: %s %s", jf.name, status, body)
            failed += 1
        except Exception as e:
            log.exception("Failed to create rubric from %s: %s", jf.name, e)
            failed += 1

    log.info(
        "Rubrics import complete. created=%d failed=%d total=%d",
        created,
        failed,
        len(files),
    )
