# importers/import_discussions.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_discussions"]


class CanvasLike(Protocol):
    session: requests.Session
    api_root: str
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def get(self, endpoint: str, **kwargs) -> Any: ...


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_text_if_exists(p: Path) -> Optional[str]:
    return p.read_text(encoding="utf-8") if p.exists() else None

def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _pick_message_html(dir_: Path, meta: Dict[str, Any]) -> str:
    rel = meta.get("html_path") or meta.get("message_path")
    candidates = [rel] if rel else []
    candidates += ["message.html", "index.html", "body.html"]
    for name in candidates:
        if not name:
            continue
        p = dir_ / name
        if p.exists():
            return _read_text_if_exists(p) or ""
    return ""


def import_discussions(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: dict[str, dict],
) -> dict[str, int]:
    """
    Import discussions:

      • POST /courses/:id/discussion_topics with body fields
      • Record id_map['discussions'][old_id] = new_id
    """
    log = get_logger(course_id=target_course_id, artifact="discussions")
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    root = export_root / "discussions"
    if not root.exists():
        log.info("nothing-to-import at %s", root)
        return counters

    id_map.setdefault("discussions", {})

    limit_env = os.getenv("IMPORT_DISCUSSIONS_LIMIT")
    limit: Optional[int] = int(limit_env) if (limit_env and limit_env.isdigit()) else None

    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue

        meta_path = d / "discussion_metadata.json"
        if not meta_path.exists():
            counters["skipped"] += 1
            log.warning("missing_metadata dir=%s", d)
            continue

        try:
            meta = _read_json(meta_path)
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed to read metadata %s: %s", meta_path, e)
            continue

        counters["total"] += 1

        title = meta.get("title") or meta.get("name")
        if not title:
            counters["skipped"] += 1
            log.warning("skipping (missing title) %s", meta_path)
            continue

        message_html = _pick_message_html(d, meta)

        payload: Dict[str, Any] = {
            "title": title,
            "message": message_html,
            "published": bool(meta.get("published", False)),
        }
        # Common options if present
        for k in [
            "delayed_post_at", "lock_at", "require_initial_post",
            "discussion_type", "group_category_id", "is_announcement",
            "allow_rating", "only_graders_can_rate", "sort_by_rating",
            "podcast_enabled", "podcast_has_student_posts"
        ]:
            if meta.get(k) is not None:
                payload[k] = meta[k]

        old_id = _coerce_int(meta.get("id"))

        endpoint = f"/api/v1/courses/{target_course_id}/discussion_topics"
        log.debug("create discussion title=%r dir=%s", title, d)
        try:
            resp = canvas.post(endpoint, json=payload)
            try:
                data = resp.json()
            except ValueError:
                data = {}
        except Exception as e:
            counters["failed"] += 1
            log.exception("failed-create title=%s: %s", title, e)
            continue

        new_id = _coerce_int(data.get("id"))

        if new_id is None and "Location" in resp.headers:
            try:
                follow = canvas.session.get(resp.headers["Location"])
                follow.raise_for_status()
                try:
                    j2 = follow.json()
                except ValueError:
                    j2 = {}
                new_id = _coerce_int(j2.get("id"))
            except Exception as e:
                log.debug("follow-location failed for discussion=%s: %s", title, e)

        if new_id is None:
            counters["failed"] += 1
            log.error("failed-create (no id) title=%s", title)
            continue

        if old_id is not None:
            id_map["discussions"][old_id] = new_id

        counters["imported"] += 1

        if limit is not None and counters["imported"] >= limit:
            log.info("IMPORT_DISCUSSIONS_LIMIT=%s reached; stopping early", limit)
            break

    log.info(
        "Discussions import complete. imported=%d skipped=%d failed=%d total=%d",
        counters["imported"], counters["skipped"], counters["failed"], counters["total"],
    )
    return counters
