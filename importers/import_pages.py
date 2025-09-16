# importers/import_pages.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

__all__ = ["import_pages"]


# ---- Protocol to decouple from exact CanvasAPI class -------------------
class CanvasLike(Protocol):
    session: requests.Session
    api_root: str  # e.g., "https://school.instructure.com/api/v1/"

    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...


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


def _find_html_file(page_dir: Path, meta: Dict[str, Any], logger) -> Optional[Path]:
    """
    Be generous in what we accept. Try (in order):
      1) Metadata hints: html_path, html, body_path, content_path
      2) Common filenames
      3) Any *.html / *.htm in the folder (pick first sorted)
    """
    # 1) metadata hints
    for key in ("html_path", "html", "body_path", "content_path"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            p = (page_dir / val).resolve()
            if p.exists():
                return p

    # 2) common names
    common = [
        "index.html",
        "body.html",
        "description.html",
        "content.html",
        "page.html",
        "index.htm",
    ]
    for name in common:
        p = page_dir / name
        if p.exists():
            return p

    # 3) any html/htm
    candidates = sorted(list(page_dir.glob("*.html")) + list(page_dir.glob("*.htm")))
    if candidates:
        return candidates[0]

    # Nothing found
    try:
        # Light debug to help diagnose folder contents
        listing = ", ".join(sorted([c.name for c in page_dir.glob("*")]))
        logger.debug("no html file found under %s; contents: %s", page_dir, listing)
    except Exception:
        pass
    return None


# Warn only once per run if exported position != server position
_POSITION_MISMATCH_WARNED = False


def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,                  # needs: post, put, session.get
    id_map: dict[str, dict],
) -> dict[str, int]:
    """
    Import wiki pages:

      • POST /courses/:id/pages with title/body/published
      • If POST returns only slug + 'Location' header, GET the Location to obtain numeric id
      • Always record:
            id_map['pages_url'][old_slug] -> new_slug
            id_map['pages'][old_id]       -> new_id   (when available)
      • If front_page: True, PUT /courses/:id/front_page after creation
      • If exported 'position' differs from server 'position', log a single warning
    """
    logger = get_logger(course_id=target_course_id, artifact="pages")
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    pages_dir = export_root / "pages"
    if not pages_dir.exists():
        logger.info("nothing-to-import at %s", pages_dir)
        return counters

    id_map.setdefault("pages", {})
    id_map.setdefault("pages_url", {})

    # Each page lives under pages/<slug-or-id>/
    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue

        meta_path = page_dir / "page_metadata.json"
        if not meta_path.exists():
            counters["skipped"] += 1
            logger.warning("missing_metadata dir=%s", page_dir)
            continue

        try:
            meta = _read_json(meta_path)
        except Exception as e:
            counters["failed"] += 1
            logger.exception("failed to read metadata %s: %s", meta_path, e)
            continue

        counters["total"] += 1

        title = meta.get("title")
        if not title:
            counters["skipped"] += 1
            logger.warning("skipping %s (missing page title)", meta_path)
            continue

        # Resolve HTML body file (robust)
        html_path = _find_html_file(page_dir, meta, logger)
        body_html: Optional[str] = None
        if html_path:
            body_html = _read_text_if_exists(html_path)

        # Fallback to metadata body/description if no file found
        if body_html is None:
            body_html = meta.get("body") or meta.get("description")

        if body_html is None:
            counters["skipped"] += 1
            logger.warning("missing_html title=%s dir=%s", title, page_dir)
            continue

        payload = {
            "title": title,
            "body": body_html,
            "published": bool(meta.get("published", False)),
        }

        old_id = _coerce_int(meta.get("id"))
        old_slug = meta.get("url") or meta.get("slug")

        # --- Create page
        try:
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/pages", json=payload)
            try:
                data = resp.json()
            except ValueError:
                data = {}
        except Exception as e:
            counters["failed"] += 1
            logger.exception("failed-create title=%s: %s", title, e)
            continue

        new_slug: Optional[str] = data.get("url")
        new_id: Optional[int] = _coerce_int(data.get("id") or data.get("page_id"))

        # Follow Location if id missing
        if new_id is None and "Location" in resp.headers:
            try:
                follow = canvas.session.get(resp.headers["Location"])
                follow.raise_for_status()
                try:
                    j2 = follow.json()
                except ValueError:
                    j2 = {}
                new_id = _coerce_int(j2.get("id") or j2.get("page_id"))
                if not new_slug:
                    new_slug = j2.get("url")
                # Prefer the followed position when available
                data = j2 or data
            except Exception as e:
                logger.debug("follow-location failed for title=%s: %s", title, e)

        if not new_slug:
            counters["failed"] += 1
            logger.error("failed-create (no slug) title=%s", title)
            continue

        # Record URL map always; record id map if we have both sides
        if old_slug:
            id_map["pages_url"][str(old_slug)] = str(new_slug)
        if old_id is not None and new_id is not None:
            id_map["pages"][old_id] = new_id

        # Position mismatch warning (once per run)
        global _POSITION_MISMATCH_WARNED
        exp_pos = meta.get("position")
        got_pos = data.get("position")
        if exp_pos is not None and got_pos is not None and exp_pos != got_pos and not _POSITION_MISMATCH_WARNED:
            logger.warning(
                "position-mismatch exported=%s server=%s slug=%s", exp_pos, got_pos, new_slug
            )
            _POSITION_MISMATCH_WARNED = True

        counters["imported"] += 1

        # Front page after creation
        if meta.get("front_page"):
            try:
                canvas.put(f"/api/v1/courses/{target_course_id}/front_page", json={"url": new_slug})
            except Exception as e:
                counters["failed"] += 1
                logger.error("failed-frontpage slug=%s: %s", new_slug, e)

    logger.info(
        "Pages import complete. imported=%d skipped=%d failed=%d total=%d",
        counters["imported"], counters["skipped"], counters["failed"], counters["total"],
    )
    return counters
