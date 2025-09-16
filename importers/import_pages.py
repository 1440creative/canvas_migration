# importers/import_pages.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from requests import HTTPError
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

def _error_detail(resp: Optional[requests.Response]) -> str:
    if not resp:
        return ""
    try:
        j = resp.json()
        if isinstance(j, dict):
            if "errors" in j:
                return json.dumps(j["errors"])
            if "message" in j:
                return str(j["message"])
            return json.dumps(j)
        return str(j)
    except Exception:
        txt = (resp.text or "").strip()
        return txt[:1000]

def _find_html_file(page_dir: Path, meta: Dict[str, Any], logger) -> Optional[Path]:
    # honor explicit hints first
    for key in ("html_path", "html", "body_path", "content_path"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            p = (page_dir / val).resolve()
            if p.exists():
                return p
    # common names
    for name in ("index.html", "body.html", "description.html", "content.html", "page.html", "index.htm"):
        p = page_dir / name
        if p.exists():
            return p
    # fallback: first *.html/htm file
    candidates = sorted(list(page_dir.glob("*.html")) + list(page_dir.glob("*.htm")))
    if candidates:
        return candidates[0]
    try:
        listing = ", ".join(sorted(c.name for c in page_dir.iterdir()))
        logger.debug("no html file found under %s; contents: %s", page_dir, listing)
    except Exception:
        pass
    return None

def _apply_timeout_from_env(logger) -> float:
    # Let users cap HTTP waits without touching utils.api
    timeout_s = float(os.getenv("CANVAS_TIMEOUT") or os.getenv("CANVAS_HTTP_TIMEOUT") or 20)
    try:
        # Monkey-patch utils.api DEFAULT_TIMEOUT so canvas.post() uses it
        import utils.api as api_mod  # type: ignore
        api_mod.DEFAULT_TIMEOUT = timeout_s
        logger.debug("HTTP timeout set to %.1fs via utils.api.DEFAULT_TIMEOUT", timeout_s)
    except Exception:
        logger.debug("utils.api not available to set DEFAULT_TIMEOUT; relying on requests defaults")
    return timeout_s

def _create_page(canvas: CanvasLike, course_id: int, wiki: Dict[str, Any]) -> requests.Response:
    """
    Canvas 'Create a Page' expects wiki_page[...] fields.
    Try JSON first, fall back to form-encoded if that 400s.
    """
    endpoint = f"/api/v1/courses/{course_id}/pages"

    # 1) JSON envelope
    try:
        resp = canvas.post(endpoint, json={"wiki_page": wiki})
        return resp
    except HTTPError as e:
        if getattr(e, "response", None) and e.response.status_code == 400:
            # 2) form-encoding fall-back
            data = {f"wiki_page[{k}]": v for k, v in wiki.items() if v is not None}
            resp2 = canvas.post(endpoint, data=data)
            return resp2
        raise

# Warn only once per run if exported position != server position
_POSITION_MISMATCH_WARNED = False

def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    id_map: dict[str, dict],
) -> dict[str, int]:
    """
    Import wiki pages from export_root/pages/<slug>/.

    - POST /courses/:id/pages with wiki_page[title/body/published]
    - If POST returns only slug + Location header, GET it to obtain numeric id
    - Record:
        id_map['pages_url'][old_slug] -> new_slug
        id_map['pages'][old_id]       -> new_id   (when available)
    - If front_page: True, PUT /courses/:id/front_page after creation
    """
    logger = get_logger(course_id=target_course_id, artifact="pages")
    counters = {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    pages_dir = export_root / "pages"
    if not pages_dir.exists():
        logger.info("nothing-to-import at %s", pages_dir)
        return counters

    # Cap HTTP wait and allow quick canary runs
    _apply_timeout_from_env(logger)
    page_limit = int(os.getenv("IMPORT_PAGES_LIMIT", "0"))
    processed = 0

    id_map.setdefault("pages", {})
    id_map.setdefault("pages_url", {})

    for page_dir in sorted(p for p in pages_dir.iterdir() if p.is_dir()):
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

        title = (meta.get("title") or "").strip()
        if not title:
            counters["skipped"] += 1
            logger.warning("skipping %s (missing page title)", meta_path)
            continue

        html_path = _find_html_file(page_dir, meta, logger)
        body_html: Optional[str] = None
        if html_path:
            body_html = _read_text_if_exists(html_path)
        if body_html is None:
            body_html = meta.get("body") or meta.get("description") or ""

        body_bytes = len((body_html or "").encode("utf-8"))
        logger.debug("create page title=%r bytes=%d dir=%s", title, body_bytes, page_dir)

        wiki_page = {
            "title": title,
            "body": body_html,
            "published": bool(meta.get("published", False)),
        }

        old_id = _coerce_int(meta.get("id"))
        old_slug = meta.get("url") or meta.get("slug")

        # --- Create page
        try:
            resp = _create_page(canvas, target_course_id, wiki_page)
            try:
                data = resp.json()
            except ValueError:
                data = {}
        except HTTPError as e:
            counters["failed"] += 1
            detail = _error_detail(getattr(e, "response", None))
            logger.error("failed-create title=%s: %s | details=%s", title, str(e), detail)
            continue
        except requests.RequestException as e:
            counters["failed"] += 1
            logger.error("network-error title=%s: %s", title, e)
            continue
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
                data = j2 or data
            except Exception as e:
                logger.debug("follow-location failed for title=%s: %s", title, e)

        if not new_slug:
            counters["failed"] += 1
            logger.error("failed-create (no slug) title=%s", title)
            continue

        if old_slug:
            id_map["pages_url"][str(old_slug)] = str(new_slug)
        if old_id is not None and new_id is not None:
            id_map["pages"][old_id] = new_id

        global _POSITION_MISMATCH_WARNED
        exp_pos = meta.get("position")
        got_pos = data.get("position")
        if exp_pos is not None and got_pos is not None and exp_pos != got_pos and not _POSITION_MISMATCH_WARNED:
            logger.warning("position-mismatch exported=%s server=%s slug=%s", exp_pos, got_pos, new_slug)
            _POSITION_MISMATCH_WARNED = True

        counters["imported"] += 1
        processed += 1

        # Front page after creation
        if meta.get("front_page"):
            try:
                canvas.put(f"/api/v1/courses/{target_course_id}/front_page", json={"url": new_slug})
            except Exception as e:
                counters["failed"] += 1
                logger.error("failed-frontpage slug=%s: %s", new_slug, e)

        if page_limit and processed >= page_limit:
            logger.info("IMPORT_PAGES_LIMIT=%d reached; stopping early", page_limit)
            break

    logger.info(
        "Pages import complete. imported=%d skipped=%d failed=%d total=%d",
        counters["imported"], counters["skipped"], counters["failed"], counters["total"],
    )
    return counters
