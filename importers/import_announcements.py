# importers/import_announcements.py
"""
Import Announcements into a Canvas course using your CanvasAPI-style wrapper.

Layout assumed per announcement:
  announcements/<slug-or-id>/
    ├─ announcement_metadata.json
    └─ (optional) description.html   # overrides metadata["message"]

Creates via:
  POST /api/v1/courses/{course_id}/discussion_topics  with is_announcement=True

Records:
  id_map["announcements"][old_id] = new_id
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Protocol
import requests
from logging_setup import get_logger


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]: ...


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


# Allowed announcement fields (subset of discussions)
_ALLOWED_FIELDS = {
    "title", "published", "pinned", "locked",
    "delayed_post_at", "lock_at",
}


def _build_announcement_payload(meta: Dict[str, Any], description_html: Optional[str]) -> Dict[str, Any]:
    ann: Dict[str, Any] = {}
    for k in _ALLOWED_FIELDS:
        if k in meta and meta[k] is not None:
            ann[k] = meta[k]

    if "name" in meta and not ann.get("title"):
        ann["title"] = meta["name"]

    if description_html is not None:
        ann["message"] = description_html
    elif meta.get("message"):
        ann["message"] = meta["message"]

    # Force it to be an announcement
    ann["is_announcement"] = True
    return ann


def import_announcements(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: Dict[str, Dict[int, int]],
) -> None:
    logger = get_logger(course_id=target_course_id, artifact="announcements")

    a_dir = export_root / "announcements"
    if not a_dir.exists():
        logger.warning("No announcements directory found at %s", a_dir)
        return

    logger.info("Starting announcements import from %s", a_dir)
    ann_id_map = id_map.setdefault("announcements", {})
    imported = skipped = failed = 0

    for meta_file in a_dir.rglob("announcement_metadata.json"):
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
            logger.warning("Skipping %s (missing title)", meta_file)
            continue

        html_rel = meta.get("html_path") or "description.html"
        html_path = meta_file.parent / html_rel
        description_html = _read_text_if_exists(html_path)

        try:
            payload = _build_announcement_payload(meta, description_html)
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/discussion_topics", json=payload)
            resp.raise_for_status()
            created = resp.json()
            new_id = _coerce_int(created.get("id"))

            if old_id is not None and new_id is not None:
                ann_id_map[old_id] = new_id

            imported += 1
            logger.info("Created announcement '%s' old_id=%s new_id=%s", title, old_id, new_id)

        except Exception as e:
            failed += 1
            logger.exception("Failed to create announcement from %s: %s", meta_file.parent, e)

    logger.info(
        "Announcements import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, imported + skipped + failed,
    )