# importers/import_rubric_links.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from logging_setup import get_logger
from utils.api import DEFAULT_TIMEOUT

__all__ = ["import_rubric_links"]

class CanvasLike:
    session: requests.Session
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None): ...
    def _full_url(self, endpoint: str) -> str: ...

# ---------- helpers ----------

def _find_links_file(export_root: Path) -> Optional[Path]:
    """
    Locate rubric_links.json (supports both correct and accidental nested layouts).
    """
    root = Path(export_root)
    candidates = [
        root / "course" / "rubric_links.json",
        root / root.name / "course" / "rubric_links.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _as_int(x: Any) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except Exception:
        return None

def _load_id_map(export_root: Path) -> Dict[str, Any]:
    """
    import_course saves id_map.json at export_root when export_root points at the course folder.
    """
    p = Path(export_root) / "id_map.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _best_assignment_id_map(id_map: Dict[str, Any]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    src = id_map.get("assignments") or {}
    for k, v in src.items():
        try:
            out[int(k)] = int(v)
        except Exception:
            continue
    return out

def _index_export_rubrics_by_id_and_title(export_root: Path) -> Dict[int, str]:
    """
    Build {old_rubric_id: title} from exported rubric files.
    Handles per-file dicts, lists, and filename-derived ids (rubric_<id>.json).
    """
    root = Path(export_root)
    dirs = [
        root / "course" / "rubrics",
        root / "rubrics",
        root / root.name / "course" / "rubrics",
    ]
    results: Dict[int, str] = {}

    def _maybe_take(obj: Dict[str, Any], fname: str) -> None:
        rid = _as_int(obj.get("id") or obj.get("rubric_id"))
        title = obj.get("title") or obj.get("title_text") or obj.get("rubric_title") or obj.get("name")
        if rid is None and fname.startswith("rubric_"):
            m = re.match(r"rubric_(\d+)", fname)
            if m:
                rid = _as_int(m.group(1))
        if rid is not None and title:
            results[rid] = title

    for d in dirs:
        if not d.exists():
            continue
        for f in d.glob("*.json"):
            data = _read_json(f)
            if data is None:
                continue
            if isinstance(data, dict):
                if "rubric" in data and isinstance(data["rubric"], dict):
                    _maybe_take(data["rubric"], f.stem)
                else:
                    _maybe_take(data, f.stem)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        _maybe_take(item, f.stem)

    return results

def _target_rubric_title_to_id(canvas: CanvasLike, course_id: int) -> Dict[str, int]:
    rubrics = canvas.get(f"/api/v1/courses/{course_id}/rubrics") or []
    out: Dict[str, int] = {}
    if isinstance(rubrics, list):
        for r in rubrics:
            rid = r.get("id")
            title = r.get("title") or r.get("title_text") or r.get("rubric_title")
            if isinstance(rid, int) and title:
                out[title] = rid
    return out

def _find_new_assignment_id(
    *,
    old_assignment_id: int,
    assignment_title: Optional[str],
    id_map_assignments: Dict[int, int],
    canvas: CanvasLike,
    course_id: int,
) -> Optional[int]:
    nid = id_map_assignments.get(old_assignment_id)
    if isinstance(nid, int):
        return nid
    if assignment_title:
        try:
            assigns = canvas.get(f"/api/v1/courses/{course_id}/assignments")
            if isinstance(assigns, list):
                for a in assigns:
                    if (a.get("name") or a.get("title")) == assignment_title:
                        return _as_int(a.get("id"))
        except Exception:
            pass
    return None

def _post_form(canvas: CanvasLike, endpoint: str, data: Dict[str, Any]) -> requests.Response:
    url = canvas._full_url(endpoint)
    headers = canvas.session.headers.copy()
    headers.pop("Content-Type", None)
    resp = canvas.session.post(url, data=data, headers=headers, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return resp

# ---------- public entrypoint ----------

def import_rubric_links(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
) -> None:
    """
    Attach rubrics to assignments in the TARGET course, using exported associations.

    Creates associations via:
      POST /api/v1/courses/:course_id/rubric_associations
      with form fields in the rubric_association[...] namespace.
    """
    log = get_logger(artifact="rubric_links_import", course_id=target_course_id)

    links_path = _find_links_file(export_root)
    if not links_path:
        log.info("No rubric_links.json associations found; nothing to attach.")
        return

    log.debug("Using rubric_links file")
    data = _read_json(links_path)
    if not data:
        log.info("rubric_links.json is empty; nothing to attach.")
        return
    if not isinstance(data, list):
        log.warning("rubric_links.json is not a list; skipping.")
        return

    source_rubric_titles = _index_export_rubrics_by_id_and_title(export_root)
    target_rubric_ids_by_title = _target_rubric_title_to_id(canvas, target_course_id)
    id_map = _load_id_map(export_root)
    id_map_assignments = _best_assignment_id_map(id_map)

    attached = 0
    skipped = 0
    failed = 0

    for assoc in data:
        if not isinstance(assoc, dict):
            skipped += 1
            continue

        src_rid = _as_int(assoc.get("rubric_id"))
        obj_type = assoc.get("object_type") or "Assignment"
        src_oid = _as_int(assoc.get("object_id"))
        assignment_title = assoc.get("assignment_title")
        use_for_grading = bool(assoc.get("use_for_grading", True))
        hide_score_total = bool(assoc.get("hide_score_total", False))
        purpose = assoc.get("purpose") or "grading"

        if obj_type != "Assignment" or src_rid is None or src_oid is None:
            skipped += 1
            continue

        rubric_title = assoc.get("rubric_title") or source_rubric_titles.get(src_rid)
        if not rubric_title:
            log.warning("No rubric title found for source rubric_id=%s; skipping", src_rid)
            skipped += 1
            continue

        new_rid = target_rubric_ids_by_title.get(rubric_title)
        if not isinstance(new_rid, int):
            log.warning("Target rubric with title '%s' not found; skipping attach", rubric_title)
            skipped += 1
            continue

        new_aid = _find_new_assignment_id(
            old_assignment_id=src_oid,
            assignment_title=assignment_title,
            id_map_assignments=id_map_assignments,
            canvas=canvas,
            course_id=target_course_id,
        )
        if not isinstance(new_aid, int):
            log.warning("No target assignment found for source assignment_id=%s (title=%r); skipping", src_oid, assignment_title)
            skipped += 1
            continue

        # IMPORTANT: Use the non-nested endpoint + include rubric_id in the form body
        endpoint = f"/api/v1/courses/{target_course_id}/rubric_associations"
        payload = {
            "rubric_association[rubric_id]": new_rid,
            "rubric_association[association_type]": "Assignment",
            "rubric_association[association_id]": new_aid,
            "rubric_association[use_for_grading]": "1" if use_for_grading else "0",
            "rubric_association[hide_score_total]": "1" if hide_score_total else "0",
            "rubric_association[purpose]": purpose,
        }

        try:
            _post_form(canvas, endpoint, payload)
            attached += 1
            log.info("Attached rubric '%s' → assignment_id=%s", rubric_title, new_aid)
        except requests.HTTPError as e:
            failed += 1
            body = e.response.text[:500] if getattr(e, "response", None) is not None else ""
            log.warning(
                "rubric_associations POST failed (rubric_title=%r, rid=%s, aid=%s): %s",
                rubric_title, new_rid, new_aid, e
            )
            if body:
                log.debug("Server body: %r", body)

    log.info(
        "Rubric links import complete. attached=%d skipped=%d failed=%d total=%d",
        attached, skipped, failed, attached + skipped + failed
    )
