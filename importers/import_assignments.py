# importers/import_assignments.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
import re

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


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _summarize_error(detail: Any) -> str:
    if isinstance(detail, dict):
        errors = detail.get("errors")
        if errors:
            try:
                return json.dumps(errors)
            except Exception:
                return str(errors)
        try:
            return json.dumps(detail)
        except Exception:
            return str(detail)

    if isinstance(detail, str):
        snippet = detail.strip()
        lower = snippet.lower()
        if "<html" in lower:
            parts: list[str] = []
            title_match = re.search(r"<title[^>]*>\s*(.*?)\s*</title>", snippet, re.I | re.S)
            if title_match:
                parts.append(f"title={_collapse_ws(title_match.group(1))}")
            h1_match = re.search(r"<h1[^>]*>\s*(.*?)\s*</h1>", snippet, re.I | re.S)
            if h1_match:
                parts.append(f"h1={_collapse_ws(h1_match.group(1))}")
            if not parts:
                text_only = re.sub(r"<[^>]+>", " ", snippet)
                parts.append(_collapse_ws(text_only)[:160])
            return "; ".join(parts)
        return _collapse_ws(snippet)[:200]

    return str(detail)


def _abs_url(api_root: str, endpoint_or_url: str) -> str:
    """
    Build an absolute URL from either a full URL or a path.
    """
    if endpoint_or_url.startswith("http://") or endpoint_or_url.startswith("https://"):
        return endpoint_or_url
    root = api_root.rstrip("/")
    if not root.endswith("/api/v1"):
        root = root + "/api/v1"
    root += "/"
    ep = endpoint_or_url.lstrip("/")
    if ep.startswith("api/v1/"):
        ep = ep[len("api/v1/") :]
    return root + ep


def _post_assignment(canvas, endpoint_path: str, payload: Dict[str, Any]) -> int:
    """
    POST the assignment. Return the new id.
      - Accepts JSON body id
      - Or follows 201 + Location (absolute or relative)
    Uses canvas.session directly for compatibility with test DummyCanvas.
    """
    url = _abs_url(canvas.api_root, endpoint_path)
    body_wrapper = {"assignment": payload}
    r = canvas.session.post(url, json=body_wrapper)
    # Do not raise here; tests often just check returned JSON/headers.

    status = getattr(r, "status_code", None)
    reason = getattr(r, "reason", "")

    # Try JSON body first
    body: Dict[str, Any] = {}
    try:
        body = r.json() or {}
    except Exception:
        body = {}

    if status and status >= 400:
        detail_raw = body if body else getattr(r, "text", "")
        detail = _summarize_error(detail_raw)
        raise RuntimeError(f"Canvas responded {status} {reason or ''}: {detail}")

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
        if isinstance(fb, dict) and fb.get("errors"):
            raise RuntimeError(
                f"Follow-up assignment fetch returned errors: {_summarize_error(fb)}"
            )

    if isinstance(body, dict) and body.get("errors"):
        raise RuntimeError(f"Canvas returned assignment errors: {body['errors']}")

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

            # Strip identifiers that are tied to the source course. Canvas will
            # reject these because the new course does not share the same
            # assignment groups or grading standards.
            for stale_key in ("assignment_group_id", "grading_standard_id", "group_category_id"):
                payload.pop(stale_key, None)

            submission_types = list(meta.get("submission_types") or [])
            if any(st == "online_quiz" for st in submission_types):
                log.info(
                    "Skipping assignment backed by quiz",
                    extra={"id": old_id, "name": name},
                )
                counters["skipped"] += 1
                continue

            new_id = _post_assignment(canvas, endpoint_path, payload)

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
