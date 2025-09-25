# importers/import_course.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

# Import steps supported by the importer 
ALL_STEPS = ["pages", "assignments", "quizzes", "files", "discussions", "modules", "rubrics", "rubric_links", "course"]


class CanvasLike(Protocol):
    api_root: str
    session: requests.Session
    def get(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...


def _int_keys(d: Dict[Any, Any]) -> Dict[Any, Any]:
    out = {}
    for k, v in (d or {}).items():
        try:
            out[int(k)] = v
        except (ValueError, TypeError):
            out[k] = v
    return out


def _normalize_id_map(m: Dict[str, Dict[Any, Any]]) -> Dict[str, Dict[Any, Any]]:
    int_maps = {"assignments", "files", "quizzes", "discussions", "pages", "modules"}
    norm = {}
    for k, v in (m or {}).items():
        if k in int_maps and isinstance(v, dict):
            norm[k] = _int_keys(v)
        else:
            norm[k] = v
    return norm


def load_id_map(path: Path) -> Dict[str, Dict[Any, Any]]:
    if path.exists():
        return _normalize_id_map(json.loads(path.read_text(encoding="utf-8")))
    return {}


def save_id_map(path: Path, id_map: Dict[str, Dict[Any, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(id_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scan_export(export_root: Path) -> Dict[str, int]:
    """
    Lightweight counts for logging.
    """
    counts: Dict[str, int] = {k: 0 for k in ALL_STEPS}
    counts["pages"] = len(list((export_root / "pages").rglob("page_metadata.json")))
    counts["assignments"] = len(list((export_root / "assignments").rglob("assignment_metadata.json")))
    counts["quizzes"] = len(list((export_root / "quizzes").rglob("quiz_metadata.json")))
    counts["files"] = len(list((export_root / "files").rglob("*.metadata.json")))
    counts["discussions"] = len(list((export_root / "discussions").rglob("discussion_metadata.json")))
    
    #rubrics: prefer export_root/rubrics - if not present,  look for export_root/<id>/rubrics
    rubrics_dir = export_root / "rubrics"
    if not rubrics_dir.exists():
        try:
            subdirs = [d for d in export_root.iterdir() if d.is_dir() and d.name.isdigit()]
            if len(subdirs) == 1:
                rubrics_dir = subdirs[0] / "rubrics"
        except Exception:
            pass
    counts["rubrics"] = len(list(rubrics_dir.glob("rubric_*.json"))) if rubrics_dir.exists() else 0
    mod_file = export_root / "modules" / "modules.json"
    if mod_file.exists():
        try:
            data = json.loads(mod_file.read_text(encoding="utf-8"))
            counts["modules"] = len(data) if isinstance(data, list) else 0
        except Exception:
            counts["modules"] = 0
    if (export_root / "course" / "course_metadata.json").exists() or (export_root / "course" / "settings.json").exists():
        counts["course"] = 1
    return counts


def import_course(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    steps: list[str] | None = None,
    id_map_path: Optional[Path] = None,
    include_quiz_questions: bool = False,
    continue_on_error: bool = True,
) -> Dict[str, Any]:
    """
    Programmatic aggregator for the whole import pipeline.
    (Blueprint import removed; must be done manually in the UI.)
    """
    steps = steps or ALL_STEPS
    log = get_logger(artifact="runner", course_id=target_course_id)

    # Lazy-import concrete importers to avoid circulars
    from importers.import_pages import import_pages
    from importers.import_assignments import import_assignments
    from importers.import_quizzes import import_quizzes
    from importers.import_files import import_files
    from importers.import_discussions import import_discussions
    from importers.import_modules import import_modules
    from importers.import_course_settings import import_course_settings
    from importers.import_rubrics import import_rubrics
    from importers.import_rubric_links import import_rubric_links
    

    id_map_path = id_map_path or (export_root / "id_map.json")
    id_map: Dict[str, Dict[Any, Any]] = load_id_map(id_map_path)

    counts: Dict[str, int] = {}
    errors: list[Dict[str, str]] = []

    log.info("Starting import (programmatic) steps=%s export_root=%s", ",".join(steps), export_root)

    for step in steps:
        try:
            if step == "pages":
                import_pages(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "assignments":
                import_assignments(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "quizzes":
                import_quizzes(target_course_id=target_course_id, export_root=export_root, canvas=canvas,
                               id_map=id_map, include_questions=include_quiz_questions)
                save_id_map(id_map_path, id_map)

            elif step == "files":
                import_files(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "discussions":
                import_discussions(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "modules":
                import_modules(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
                save_id_map(id_map_path, id_map)
                
            elif step == "rubrics":
                
                import_rubrics(target_course_id=target_course_id, export_root=export_root, canvas=canvas)
                save_id_map(id_map_path, id_map)
            
            elif step == "rubric_links":
                import_rubric_links(target_course_id=target_course_id, export_root=export_root, canvas=canvas)
                save_id_map(id_map_path, id_map)

            elif step == "course":
                import_course_settings(
                    target_course_id=target_course_id, 
                    export_root=export_root, 
                    canvas=canvas,
                )

            else:
                log.warning("Unknown step '%s' — skipping", step)
                continue

            step_counts = scan_export(export_root)
            counts[step] = step_counts.get(step, 0)
            log.info("✓ step complete", extra={"step": step, "count": counts[step]})
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            errors.append({"step": step, "error": msg})
            log.exception("✗ step failed", extra={"step": step, "error": str(e)})
            if not continue_on_error:
                break

    log.info("Programmatic import complete", extra={"counts": counts, "errors": len(errors)})
    return {"counts": counts, "errors": errors}
