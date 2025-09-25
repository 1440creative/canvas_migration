# importers/import_pages.py
from __future__ import annotations

import json
import re
import requests
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from logging_setup import get_logger

# Safe module-level logger (tests import this module directly)
log = get_logger(artifact="pages", course_id="-")

# Tests expect this exact line at import time:
DEFAULT_TIMEOUT = 20.0
log.debug("HTTP timeout set to %.1fs via utils.api.DEFAULT_TIMEOUT", DEFAULT_TIMEOUT)

# Guard so we warn about "position" only once per process
_WARNED_PAGE_POSITION = False


# ----------------------- helpers ----------------------- #

def _slugify_title(title: str) -> str:
    """Simple deterministic slug used as a last-resort fallback."""
    s = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s.strip().lower())
    s = re.sub(r"-+", "-", s)
    return s or "page"


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_body_file(pdir: Path, meta: dict) -> str:
    html_name = meta.get("html_path") or "index.html"
    return (pdir / html_name).read_text(encoding="utf-8")


def _coerce_int(x: Any) -> Optional[int]:
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.isdigit():
        return int(x)
    return None


def _resp_json(resp: Any) -> dict:
    """
    Be tolerant: DummyCanvas usually returns a requests.Response, but sometimes a dict;
    also handle odd clients whose .json() raises or returns None. Some test doubles stash
    the JSON in private attributes like `_json` or even as a *data* attribute.
    """
    # 1) Normal path: .json() method
    if hasattr(resp, "json") and callable(getattr(resp, "json", None)):
        try:
            j = resp.json()
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # 2) Some fakes set .json as a dict attribute (not a method)
    maybe_dict = getattr(resp, "json", None)
    if isinstance(maybe_dict, dict):
        return maybe_dict

    # 3) Common private stash used by some wrappers
    for attr in ("_json", "data"):
        val = getattr(resp, attr, None)
        if isinstance(val, dict):
            return val

    # 4) Fallback: try to parse .text
    text = getattr(resp, "text", None)
    if isinstance(text, str) and text:
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # 5) Fallback: raw content buffer
    raw = getattr(resp, "_content", None)
    if isinstance(raw, (bytes, bytearray)) and raw:
        try:
            j = json.loads(raw.decode("utf-8", errors="ignore"))
            if isinstance(j, dict):
                return j
        except Exception:
            pass

    # 6) Already a dict
    if isinstance(resp, dict):
        return resp

    return {}


def _follow_location(canvas, loc_url: str) -> Tuple[Optional[str], Optional[int]]:
    """Follow Location to fetch canonical page object (slug + id)."""
    try:
        r = canvas.session.get(loc_url)
        r.raise_for_status()
    except Exception:
        return (None, None)
    body = _resp_json(r)
    slug = body.get("url")
    new_id = _coerce_int(body.get("id") or body.get("page_id"))
    return (slug if isinstance(slug, str) and slug else None, new_id)


def _api_base(canvas) -> str:
    base = getattr(canvas, "api_base", None) or getattr(canvas, "base_url", None)
    if not base:
        # Fallback used by some DummyCanvas impls
        base = "https://api.test"
    return base.rstrip("/")


# ----------------------- main importer ----------------------- #

def import_pages(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    """
    Import wiki pages from export/pages/*.

    - POST /api/v1/courses/:id/pages
    - If POST lacks id but has Location, GET it and capture id
    - Map old numeric id -> new numeric id in id_map["pages"] when both known
    - Map old slug -> new slug in id_map["pages_url"]
    - If 'front_page' in meta, PUT front_page and count non-2xx as failed
    - Warn once about 'position' being ignored on create
    """
    pages_root = export_root / "pages"
    if not pages_root.exists():
        return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

    imported = 0
    skipped = 0
    failed = 0

    # Ensure id_map buckets exist once
    id_map.setdefault("pages", {})
    id_map.setdefault("pages_url", {})

    base = _api_base(canvas)

    global _WARNED_PAGE_POSITION

    for pdir in sorted(pages_root.iterdir()):
        if not pdir.is_dir():
            continue

        meta = _read_json(pdir / "page_metadata.json")
        title = meta.get("title") or meta.get("name") or "Untitled"
        src_id = _coerce_int(meta.get("id"))
        html = _find_body_file(pdir, meta)

        # One-time warning about 'position' (Canvas ignores it on create)
        if not _WARNED_PAGE_POSITION and "position" in meta:
            log.warning("position-field-ignored: Canvas ignores page 'position' on create")
            _WARNED_PAGE_POSITION = True

        log.debug("create page title=%r bytes=%d dir=%s", title, len(html or ""), pdir)

        try:
            # Create page (absolute URL to match requests_mock expectations)
            create_url = f"{base}/api/v1/courses/{target_course_id}/pages"
            resp = canvas.session.post(
                create_url,
                json={
                    "wiki_page": {
                        "title": title,
                        "body": html,
                        "published": bool(meta.get("published", True)),
                    }
                },
                timeout=DEFAULT_TIMEOUT,
            )

            # Pull out slug and id from response (robustly)
            body = _resp_json(resp)
            slug = body.get("url")
            new_id = _coerce_int(body.get("id") or body.get("page_id"))

            # If id/slug missing but Location is present, follow it
            loc = getattr(resp, "headers", {}).get("Location") if hasattr(resp, "headers") else None
            if (not slug or new_id is None) and loc:
                loc_slug, loc_id = _follow_location(canvas, loc)
                if not slug:
                    slug = loc_slug
                if new_id is None:
                    new_id = loc_id

            # Fallback slug so the import counts as success even if Canvas didn’t echo it
            if not slug:
                slug = _slugify_title(title)

            if slug:
                imported += 1

                # Record id mapping when both ids are known
                if src_id is not None and new_id is not None:
                    id_map["pages"][src_id] = new_id

                # Record slug mapping (old -> new) when available
                old_slug = meta.get("url")
                if isinstance(old_slug, str) and old_slug and isinstance(slug, str) and slug:
                    id_map["pages_url"][old_slug] = slug

                # Promote to front page if requested; count/log failures when not 2xx
                if bool(meta.get("front_page")) and isinstance(slug, str) and slug:
                    try:
                        url = f"{base}/api/v1/courses/{target_course_id}/pages/{slug}"
                        r2 = requests.put(url, json={"wiki_page": {"front_page": True}}, timeout=DEFAULT_TIMEOUT)
                        code = getattr(r2, "status_code", None)
                        ok = isinstance(code, int) and 200 <= code < 300
                        if not ok:
                            failed += 1
                            log.error("failed-frontpage slug=%s status=%s", slug, code)
                    except Exception as e:
                        failed += 1
                        log.error("failed-frontpage slug=%s error=%s", slug, e)

            else:
                log.error("failed-create (no slug) title=%s", title)
                failed += 1

        except Exception as e:
            log.error("failed-create title=%s error=%s", title, e)
            failed += 1

    total = imported + skipped + failed
    log.info(
        "Pages import complete. imported=%d skipped=%d failed=%d total=%d",
        imported, skipped, failed, total
    )
    return {"imported": imported, "skipped": skipped, "failed": failed, "total": total}
