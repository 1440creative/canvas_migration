# importers/import_assignments.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
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


def _post_assignment(canvas, endpoint_path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """
    POST the assignment. Return the new id and response JSON payload.
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
        return int(body["id"]), body

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
            return int(fb["id"]), fb
        if isinstance(fb, dict) and fb.get("errors"):
            raise RuntimeError(
                f"Follow-up assignment fetch returned errors: {_summarize_error(fb)}"
            )

    if isinstance(body, dict) and body.get("errors"):
        raise RuntimeError(f"Canvas returned assignment errors: {body['errors']}")

    raise RuntimeError("Create assignment did not return an id")


def _extract_discussion_id(assignment: Dict[str, Any]) -> Optional[int]:
    if not isinstance(assignment, dict):
        return None
    discussion = assignment.get("discussion_topic")
    if isinstance(discussion, dict):
        did = discussion.get("id")
        try:
            return int(did)
        except (TypeError, ValueError):
            pass
    did = assignment.get("discussion_topic_id")
    try:
        if did is not None:
            return int(did)
    except (TypeError, ValueError):
        pass
    # Canvas sometimes returns discussion_topic as URL or string
    did = assignment.get("discussion_topic")
    try:
        if isinstance(did, int):
            return int(did)
        if isinstance(did, str) and did.isdigit():
            return int(did)
    except (TypeError, ValueError):
        pass
    return None


def _fetch_assignment_detail(canvas, endpoint_path: str) -> Dict[str, Any]:
    url = _abs_url(canvas.api_root, endpoint_path)
    resp = canvas.session.get(url)
    status = getattr(resp, "status_code", None)
    body: Dict[str, Any] = {}
    try:
        body = resp.json() or {}
    except Exception:
        body = {}
    if status and status >= 400:
        detail_raw = body if body else getattr(resp, "text", "")
        detail = _summarize_error(detail_raw)
        raise RuntimeError(f"Canvas responded {status}: {detail}")
    return body


def _load_discussion_assignment_map(export_root: Path) -> Dict[int, int]:
    disc_map: Dict[int, int] = {}
    disc_root = export_root / "discussions"
    if not disc_root.exists():
        return disc_map
    for meta_path in sorted(disc_root.glob("**/discussion_metadata.json")):
        meta = _read_json(meta_path)
        if not meta:
            continue
        try:
            assignment_id = int(meta.get("assignment_id"))
            discussion_id = int(meta.get("id"))
        except (TypeError, ValueError):
            continue
        disc_map[assignment_id] = discussion_id
    return disc_map


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
    id_map.setdefault("discussions", {})

    discussion_lookup = _load_discussion_assignment_map(export_root)

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

            # Remap assignment_group_id when the importer has already created groups.
            if "assignment_group_id" in payload:
                group_mapping = id_map.get("assignment_groups") if isinstance(id_map, dict) else None
                mapped_id = None
                if isinstance(group_mapping, dict):
                    raw_old_id = meta.get("assignment_group_id")
                    lookup_keys = []
                    if raw_old_id is not None:
                        lookup_keys.append(raw_old_id)
                        try:
                            lookup_keys.append(int(raw_old_id))
                        except (TypeError, ValueError):
                            pass
                    for key in lookup_keys:
                        if key in group_mapping:
                            mapped_id = group_mapping[key]
                            break
                    if mapped_id is None:
                        for key in lookup_keys:
                            mapped_id = group_mapping.get(str(key))
                            if mapped_id is not None:
                                break
                if mapped_id is not None:
                    try:
                        payload["assignment_group_id"] = int(mapped_id)
                    except (TypeError, ValueError):
                        payload.pop("assignment_group_id", None)
                else:
                    payload.pop("assignment_group_id", None)

            # Strip identifiers that are tied to the source course. Canvas will
            # reject these because the new course does not share the same
            # grading standards or group categories.
            for stale_key in ("grading_standard_id", "group_category_id"):
                payload.pop(stale_key, None)

            submission_types = list(meta.get("submission_types") or [])
            if any(st == "online_quiz" for st in submission_types):
                log.info(
                    "Skipping assignment backed by quiz",
                    extra={"id": old_id, "name": name},
                )
                counters["skipped"] += 1
                continue

            new_id, assignment_body = _post_assignment(canvas, endpoint_path, payload)

            if isinstance(old_id, int):
                id_map["assignments"][int(old_id)] = int(new_id)

            # Map graded discussion ids for module importer
            if isinstance(old_id, int) and old_id in discussion_lookup:
                src_discussion_id = discussion_lookup[old_id]
                new_discussion_id = _extract_discussion_id(assignment_body)
                if new_discussion_id is None:
                    try:
                        detail_endpoint = f"/courses/{target_course_id}/assignments/{new_id}"
                        assignment_detail = _fetch_assignment_detail(canvas, detail_endpoint)
                        new_discussion_id = _extract_discussion_id(assignment_detail)
                    except Exception as err:
                        log.warning(
                            "Failed to resolve discussion id for graded discussion",
                            extra={
                                "assignment_id": old_id,
                                "new_assignment_id": new_id,
                                "error": str(err),
                            },
                        )
                        new_discussion_id = None
                if new_discussion_id is not None:
                    id_map["discussions"][src_discussion_id] = int(new_discussion_id)
                else:
                    log.warning(
                        "Missing discussion mapping for graded discussion assignment",
                        extra={"assignment_id": old_id, "new_assignment_id": new_id},
                    )

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
