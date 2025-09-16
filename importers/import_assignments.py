# importers/import_assignments.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_assignments"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def get(self, endpoint: str, **kwargs) -> Any: ...


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_text_if_exists(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8") if path.exists() else None

def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _pick_desc_html(dir_: Path, meta: Dict[str, Any]) -> Optional[str]:
    # honor explicit path if present; otherwise common fallbacks
    rel = meta.get("html_path") or meta.get("description_path")
    candidates = [rel] if rel else []
    candidates += ["description.html", "index.html", "body.html"]
    for name in candidates:
        if not name:
            continue
        p = dir_ / name
        if p.exists():
            return _read_text_if_exists(p)
    return None


def import_assignments(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: dict[str, dict],
) -> dict[str, int]:
    """
    Import assignments:

      • POST /courses/:id/assignments with {"assignment": {...}}
      • If POST returns Location and no id, GET the Location
      • Record:
           id_map['assignments'][old_id] -> new_id
    """
    log = get_logger(course_id=target_course_id, artifact="assignments")
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    assign_dir = export_root / "assignments"
    if not assign_dir.exists():
        log.info("nothing-to-import at %s", assign_dir)
        return counters

    id_map.setdefault("assignments", {})

    # Optional limiter for debug sessions
    limit_env = os.getenv("IMPORT_ASSIGNMENTS_LIMIT")
    limit: Optional[int] = int(limit_env) if (limit_env and limit_env.isdigit()) else None

    for item in sorted(assign_dir.iterdir()):
        if not item.is_dir():
            continue

        meta_path = item / "assignment_metadata.json"
        if not meta_path.exists():
            counters["skipped"] += 1
            log.warning("missing_metadata dir=%s", item)
            continue

        try:
            meta = _read_json(meta_path)
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed to read metadata %s: %s", meta_path, e)
            continue

        counters["total"] += 1

        name = meta.get("name") or meta.get("title")
        if not name:
            counters["skipped"] += 1
            log.warning("skipping (missing name) %s", meta_path)
            continue

        desc_html = _pick_desc_html(item, meta) or ""
        assignment: Dict[str, Any] = {
            "name": name,
            "description": desc_html,
            "published": bool(meta.get("published", False)),
        }

        # common optional fields if present
        for k in [
            "points_possible", "grading_type", "due_at", "lock_at", "unlock_at",
            "submission_types", "allowed_attempts", "peer_reviews",
            "omit_from_final_grade", "assignment_group_id",
            "muted", "position", "time_estimate"
        ]:
            if meta.get(k) is not None:
                assignment[k] = meta[k]

        old_id = _coerce_int(meta.get("id"))

        endpoint = f"/api/v1/courses/{target_course_id}/assignments"
        log.debug("create assignment name=%r dir=%s", name, item)
        try:
            resp = canvas.post(endpoint, json={"assignment": assignment})
            try:
                data = resp.json()
            except ValueError:
                data = {}
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed-create name=%s: %s", name, e)
            continue

        new_id = _coerce_int(data.get("id"))

        # Follow Location when needed
        if new_id is None and "Location" in resp.headers:
            try:
                follow = canvas.session.get(resp.headers["Location"])
                follow.raise_for_status()
                try:
                    j2 = follow.json()
                except ValueError:
                    j2 = {}
                new_id = _coerce_int(j2.get("id"))
                data = j2 or data
            except Exception as e:
                log.debug("follow-location failed for assignment=%s: %s", name, e)

        if new_id is None:
            counters["failed"] += 1
            log.error("failed-create (no id) name=%s", name)
            continue

        if old_id is not None:
            id_map["assignments"][old_id] = new_id

        counters["imported"] += 1

        if limit is not None and counters["imported"] >= limit:
            log.info("IMPORT_ASSIGNMENTS_LIMIT=%s reached; stopping early", limit)
            break

    log.info(
        "Assignments import complete. imported=%d skipped=%d failed=%d total=%d",
        counters["imported"], counters["skipped"], counters["failed"], counters["total"],
    )
    return counters
