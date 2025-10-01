# importers/import_assignments.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from logging_setup import get_logger


def _read_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _choose_description(a_dir: Path, meta: Dict[str, Any]) -> Optional[str]:
    """
    Prefer explicit meta['html_path'], else try common names (include index.html).
    """
    html_path = meta.get("html_path")
    if isinstance(html_path, str) and html_path:
        t = _read_text(a_dir / html_path)
        if t is not None:
            return t

    for name in ("description.html", "index.html", "body.html", "message.html"):
        t = _read_text(a_dir / name)
        if t is not None:
            return t
    return None


def _abs_url(api_root: str, endpoint_or_url: str) -> str:
    """
    Build an absolute URL from either a full URL or a path.
    """
    if endpoint_or_url.startswith("http://") or endpoint_or_url.startswith("https://"):
        return endpoint_or_url
    # ensure api_root ends with slash for urljoin to work intuitively
    root = api_root if api_root.endswith("/") else api_root + "/"
    ep = endpoint_or_url[1:] if endpoint_or_url.startswith("/") else endpoint_or_url
    return urljoin(root, ep)


def _post_assignment(canvas, endpoint_path: str, payload: Dict[str, Any]) -> int:
    """
    POST the assignment. Return the new id.
      - Accepts JSON body id
      - Or follows 201 + Location (absolute or relative)
    Uses canvas.session directly for compatibility with test DummyCanvas.
    """
    url = _abs_url(canvas.api_root, endpoint_path)
    r = canvas.session.post(url, json=payload)
    # Do not raise here; tests often just check returned JSON/headers.

    # Try JSON body first
    body: Dict[str, Any] = {}
    try:
        body = r.json() or {}
    except Exception:
        body = {}

    if isinstance(body.get("id"), int):
        return int(body["id"])

    # Fallback: follow Location header
    loc = r.headers.get("Location") or r.headers.get("location")
    if loc:
        follow_url = _abs_url(canvas.api_root, loc)
        fr = canvas.session.get(follow_url)
        try:
            fb = fr.json() or {}
        except Exception:
            fb = {}
        if isinstance(fb.get("id"), int):
            return int(fb["id"])

    raise RuntimeError("Create assignment did not return an id")


def import_assignments(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    """
    Import assignments from export_root into the target course.

    Returns counters: {"imported": N, "failed": M, "skipped": K}
    Also updates id_map["assignments"][old_id] = new_id.
    """
    log = get_logger(artifact="assignments", course_id=target_course_id)
    base = export_root / "assignments"

    counters = {"imported": 0, "failed": 0, "skipped": 0}

    if not base.exists():
        log.info("No assignments directory found; nothing to import.")
        return counters

    meta_paths = list(base.rglob("assignment_metadata.json"))
    if not meta_paths:
        log.info("No assignment metadata found under %s", base)
        return counters

    id_map.setdefault("assignments", {})

    endpoint_path = f"/api/v1/courses/{target_course_id}/assignments"

    for meta_path in sorted(meta_paths):
        a_dir = meta_path.parent
        try:
            meta = _read_json(meta_path)
            old_id = meta.get("id")

            # Build payload
            payload: Dict[str, Any] = {}
            name = meta.get("name") or meta.get("title") or a_dir.name
            payload["name"] = name

            desc = _choose_description(a_dir, meta)
            if desc is not None:
                payload["description"] = desc

            # Common optional fields if present
            for key in (
                "due_at",
                "lock_at",
                "unlock_at",
                "points_possible",
                "grading_type",
                "submission_types",
                "allowed_attempts",
                "published",
                "peer_reviews",
                "automatic_peer_reviews",
                "peer_review_count",
                "peer_reviews_assign_at",
                "group_category_id",
                "group_assignment",
                "notify_of_update",
                "muted",
                "grading_standard_id",
                "omit_from_final_grade",
                "only_visible_to_overrides",
                "moderated_grading",
                "grader_count",
                "grader_selection_strategy",
                "intra_group_peer_reviews",
                "anonymous_peer_reviews",
                "anonymous_grading",
                "grade_group_students_individually",
                "anonymous_submissions",
                "assignment_group_id",
                "external_tool_tag_attributes",
                "turnitin_enabled",
                "vericite_enabled",
            ):
                if key in meta:
                    payload[key] = meta[key]

            # Try plain payload, then nested {"assignment": payload}
            try:
                new_id = _post_assignment(canvas, endpoint_path, payload)
            except Exception:
                new_id = _post_assignment(canvas, endpoint_path, {"assignment": payload})

            if isinstance(old_id, int):
                id_map["assignments"][int(old_id)] = int(new_id)

            counters["imported"] += 1
            log.info(
                "Created assignment",
                extra={"old_id": old_id, "new_id": new_id, "name": name},
            )
        except Exception as e:
            counters["failed"] += 1
            log.error("failed-create (no id) name=%s", meta.get("name") or a_dir.name)
            log.exception("Failed to create assignment from %s: %s", a_dir, e)

    log.info(
        "Assignments import complete.",
        extra={
            "imported": counters["imported"],
            "failed": counters["failed"],
            "skipped": counters["skipped"],
            "total": len(meta_paths),
        },
    )
    return counters
