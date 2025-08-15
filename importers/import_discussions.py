# importers/import_discussions.py
"""
Import Discussions into a Canvas course using your CanvasAPI-style wrapper.

Layout assumed per discussion:
  discussions/<slug-or-id>/
    ├─ discussion_metadata.json
    └─ (optional) description.html   # overrides metadata["message"]

Creates via:
  POST /api/v1/courses/{course_id}/discussion_topics

Records:
  id_map["discussions"][old_id] = new_id
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_discussions"]


# ---- Protocol to decouple from your exact CanvasAPI class -------------------
class CanvasLike(Protocol):
    session: requests.Session
    api_root: str  # e.g., "https://school.instructure.com/api/v1/"

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


# ---- Helpers ----------------------------------------------------------------
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


_ALLOWED_FIELDS = {
    # Identity / visibility
    "title", "published", "pinned", "locked",
    # Flow & behavior
    "discussion_type", "require_initial_post",
    # Timing
    "delayed_post_at", "lock_at",
    # Rating
    "allow_rating", "only_graders_can_rate", "sort_by_rating",
    # Group discussions
    "group_category_id",
    # Misc (Canvas accepts these on discussion_topics)
    "podcast_enabled", "podcast_has_student_posts", "podcast_itunes_url",
    "is_announcement",
}

# A conservative subset for graded discussions
_ALLOWED_ASSIGNMENT_FIELDS = {
    "points_possible", "grading_type", "due_at", "lock_at", "unlock_at",
    "assignment_group_id", "published", "peer_reviews", "notify_of_update",
    "only_visible_to_overrides",
}


def _build_discussion_payload(meta: Dict[str, Any], description_html: Optional[str]) -> Dict[str, Any]:
    disc: Dict[str, Any] = {}
    # Copy allowed top-level discussion fields
    for k in _ALLOWED_FIELDS:
        if k in meta and meta[k] is not None:
            disc[k] = meta[k]

    # Title is normalized to "title"
    if "name" in meta and not disc.get("title"):
        disc["title"] = meta["name"]

    # Message / body: prefer file HTML, then metadata["message"] or ["description"]
    if description_html is not None:
        disc["message"] = description_html
    else:
        msg = meta.get("message") or meta.get("description")
        if msg is not None:
            disc["message"] = msg

    # Optional graded discussion
    asg = meta.get("assignment")
    if isinstance(asg, dict):
        envelope = {}
        for k in _ALLOWED_ASSIGNMENT_FIELDS:
            if k in asg and asg[k] is not None:
                envelope[k] = asg[k]
        if envelope:
            disc["assignment"] = envelope

    return disc


# ---- Public entrypoint ------------------------------------------------------
def import_discussions(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
) -> None:
    """
    Create discussions from export_root/discussions into the target course and update id_map.

    Produces/updates:
        id_map["discussions"] : Dict[int(old_discussion_id) -> int(new_discussion_id)]
    """
    logger = get_logger(course_id=target_course_id, artifact="discussions")

    d_dir = export_root / "discussions"
    if not d_dir.exists():
        logger.warning("No discussions directory found at %s", d_dir)
        return

    logger.info("Starting discussions import from %s", d_dir)

    disc_id_map = id_map.setdefault("discussions", {})
    imported = 0
    skipped = 0
    failed = 0

    for meta_file in d_dir.rglob("discussion_metadata.json"):
        try:
            meta = _read_json(meta_file)
        except Exception as e:
            failed += 1
            logger.exception("Failed to read %s: %s", meta_file, e)
            continue

        old_id = _coerce_int(meta.get("id"))
        title = meta.get("title") or meta.get("name")
        if not title:
            skipped += 1
            logger.warning("Skipping %s (missing discussion title)", meta_file)
            continue

        # Resolve HTML body (optional)
        html_rel = meta.get("html_path") or "description.html"
        html_path = meta_file.parent / html_rel
        description_html = _read_text_if_exists(html_path)

        try:
            payload = _build_discussion_payload(meta, description_html)
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/discussion_topics", json=payload)
            resp.raise_for_status()
            created = resp.json()
            new_id = _coerce_int(created.get("id"))

            if old_id is not None and new_id is not None:
                disc_id_map[old_id] = new_id

            imported += 1
            logger.info("Created discussion '%s' old_id=%s new_id=%s", title, old_id, new_id)

        except Exception as e:
            failed += 1
            logger.exception("Failed to create discussion from %s: %s", meta_file.parent, e)

    logger.info(
        "Discussions import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, imported + skipped + failed
    )
