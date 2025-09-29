# importers/import_discussions.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from logging_setup import get_logger


def _read_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_html(d: Path, meta: Dict[str, Any], *, course_root: Path | None = None) -> str:
    """Load discussion HTML, tolerating html_path relative to course root."""
    html_name = meta.get("html_path")

    candidates = []
    if isinstance(html_name, str) and html_name:
        if course_root is not None and "/" in html_name:
            candidates.append(course_root / html_name)
        candidates.append(d / html_name)

    candidates.append(d / "index.html")
    candidates.append(d / "body.html")

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return candidate.read_text(encoding="utf-8")
        except Exception:
            continue

    return ""


def import_discussions(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]] | None = None,
) -> Dict[str, int]:
    """
    Import non-announcement discussions from export_root/<course_id>/discussions/*

    - POST {api_root}/api/v1/courses/:course_id/discussion_topics
    - Accept both "id in response body" and 201 + Location follow
    - Skip items that are announcements (handled by announcements importer)
    - Record id_map["discussions"][<source_id>] = <new_id>
    """
    log = get_logger(artifact="discussions", course_id=target_course_id)
    # IMPORTANT: only create a new dict if None; don't replace a provided (possibly empty) dict
    id_map = id_map if id_map is not None else {}
    id_map.setdefault("discussions", {})

    disc_root = export_root / "discussions"
    if not disc_root.exists():
        log.info("No discussions export directory; nothing to import")
        return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    imported = skipped = failed = total = 0

    # Build absolute endpoint to match tests' requests_mock registrations
    api_root = (getattr(canvas, "api_root", "") or "").rstrip("/")
    abs_endpoint = (
        f"{api_root}/api/v1/courses/{target_course_id}/discussion_topics"
        if api_root
        else f"/api/v1/courses/{target_course_id}/discussion_topics"
    )

    for d in sorted(disc_root.iterdir()):
        if not d.is_dir():
            continue
        meta = _read_json(d / "discussion_metadata.json")
        if not meta:
            continue

        total += 1

        # Skip announcements; handled by the announcements importer
        if bool(meta.get("is_announcement")):
            skipped += 1
            continue

        title = meta.get("title") or "Discussion"
        message_html = _read_html(d, meta, course_root=export_root)
        published = bool(meta.get("published"))
        delayed_post_at = meta.get("delayed_post_at")

        payload: Dict[str, Any] = {
            "title": title,
            "message": message_html,
            "published": published,
            "is_announcement": False,
        }
        if delayed_post_at:
            payload["delayed_post_at"] = delayed_post_at

        try:
            # Use session.post with ABSOLUTE URL so mocks match exactly
            r = canvas.session.post(abs_endpoint, json=payload)  # type: ignore[attr-defined]

            # Try to extract id from JSON body
            new_id = None
            try:
                body = r.json()  # requests_mock supports .json()
                if isinstance(body, dict):
                    new_id = body.get("id")
            except Exception:
                pass

            # If no id, try following Location header (don't isinstance-check headers)
            if not new_id:
                loc = getattr(r, "headers", {}).get("Location")
                if loc:
                    follow = canvas.session.get(loc)  # type: ignore[attr-defined]
                    follow.raise_for_status()
                    try:
                        fbody = follow.json()
                        if isinstance(fbody, dict):
                            new_id = fbody.get("id")
                    except Exception:
                        new_id = None

            if not new_id:
                log.error("failed-create (no id) title=%s", title)
                failed += 1
                continue

            imported += 1
            src_id = meta.get("id")
            if isinstance(src_id, int):
                id_map["discussions"][src_id] = int(new_id)

        except Exception as e:
            failed += 1
            log.exception("Failed to import discussion '%s': %s", title, e)

    log.info(
        "Discussions import complete. imported=%d skipped=%d failed=%d total=%d",
        imported,
        skipped,
        failed,
        total,
    )
    return {"imported": imported, "skipped": skipped, "failed": failed, "total": total}
