# export/export_home.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from logging_setup import get_logger

def export_home(course_id: int, export_root: Path, api) -> Dict[str, Any]:
    """
    Writes course/home.json with:
      {"default_view": "...", "front_page": {"page_id": ..., "url": "...", "title": "..."}}
    If default_view != "wiki", only "default_view" is written.
    """
    log = get_logger(artifact="home_export", course_id=course_id)
    outdir = export_root / str(course_id) / "course"
    outdir.mkdir(parents=True, exist_ok=True)

    course = api.get(f"/api/v1/courses/{course_id}")
    default_view = course.get("default_view")

    out: Dict[str, Any] = {"default_view": default_view}

    if default_view == "wiki":
        try:
            # The front page (wiki page) has page_id/url/title
            front = api.get(f"/api/v1/courses/{course_id}/front_page")
            out["front_page"] = {
                "page_id": front.get("page_id"),
                "url": front.get("url"),
                "title": front.get("title"),
            }
        except Exception as e:
            log.warning("Could not fetch front_page: %s", e)

    (outdir / "home.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    log.info("Wrote %s", outdir / "home.json")
    return out
