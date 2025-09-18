# export/export_rubrics.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from logging_setup import get_logger


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _as_list(x):
    if isinstance(x, list):
        return x
    if x is None:
        return []
    return [x]


def export_rubrics(course_id: int, export_root: Path, api) -> List[Dict[str, Any]]:
    """
    Export rubrics associated with a course into:
      <export_root>/<course_id>/rubrics/rubric_<id>.json

    Returns a list of simple rubric metas (id/title).
    """
    log = get_logger(artifact="rubrics_export", course_id=course_id)
    out_dir = export_root / str(course_id) / "rubrics"
    _ensure_dir(out_dir)

    metas: List[Dict[str, Any]] = []

    try:
        # Prefer the course-scoped listing; include associations so we know how they’re used.
        rubrics = api.get(f"/api/v1/courses/{course_id}/rubrics", params={"include[]": "associations"})
    except Exception as e:
        log.warning("Failed to list course rubrics: %s", e)
        rubrics = []

    if not isinstance(rubrics, list):
        rubrics = _as_list(rubrics)

    for r in rubrics:
        rid = r.get("id")
        title = r.get("title") or r.get("points_possible")  # fallback just so something shows
        # Try to fetch a fully-detailed copy (criteria often come from the rubric detail endpoint)
        full = r
        try:
            detail = api.get(f"/api/v1/rubrics/{rid}", params={"include[]": ["criteria", "associations"]})
            if isinstance(detail, dict):
                full = detail
        except Exception:
            pass  # keep the list item if detail fails

        # Write one file per rubric
        (out_dir / f"rubric_{rid}.json").write_text(
            __import__("json").dumps(
                {
                    "course_id": course_id,
                    "rubric": full,  # keep the raw object for max fidelity
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        metas.append({"id": rid, "title": title})

    # Optional index
    (out_dir / "index.json").write_text(
        __import__("json").dumps(metas, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    log.info("Exported %d rubrics", len(metas))
    return metas
