# importers/import_course.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger

# Import steps supported by the importer 
ALL_STEPS = ["pages", "assignments", "quizzes", "files", "discussions", "announcements", "modules", "rubrics", "rubric_links", "course"]


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
    from importers.import_announcements import import_announcements
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

            elif step == "announcements":
                import_announcements(target_course_id=target_course_id, export_root=export_root, canvas=canvas, id_map=id_map)
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
                    id_map=id_map,
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

    try:
        _postprocess_html_content(
            canvas=canvas,
            export_root=export_root,
            target_course_id=target_course_id,
            id_map=id_map,
        )
    except Exception as exc:
        log.warning("HTML post-processing skipped", extra={"error": str(exc)})

    return {"counts": counts, "errors": errors}


def _normalize_numeric_map(raw: Dict[Any, Any] | None) -> Dict[int, int]:
    normalized: Dict[int, int] = {}
    for key, value in (raw or {}).items():
        try:
            old_id = int(key)
        except (TypeError, ValueError):
            continue
        try:
            new_id = int(value)
        except (TypeError, ValueError):
            continue
        normalized[old_id] = new_id
    return normalized


def _replace_numeric_links(
    html: str,
    *,
    resource: str,
    mapping: Dict[int, int],
    source_course_id: int,
    target_course_id: int,
    include_global: bool = False,
) -> str:
    if not mapping:
        return html

    def _lookup(old: str) -> Optional[int]:
        try:
            old_int = int(old)
        except (TypeError, ValueError):
            return None
        return mapping.get(old_int)

    def _sub(pattern: re.Pattern[str], text: str) -> str:
        def _repl(match: re.Match[str]) -> str:
            prefix = match.group("prefix")
            old_id = match.group("id")
            tail = match.group("tail") or ""
            new_id = _lookup(old_id)
            if new_id is None:
                return match.group(0)
            return f"{prefix}{target_course_id}/{resource}/{new_id}{tail}"

        return pattern.sub(_repl, text)

    course_pattern = re.compile(
        rf'(?P<prefix>(?:https?://[^"\'\s]+)?/courses/){source_course_id}/{resource}/(?P<id>\d+)(?P<tail>[^"\'\s]*)'
    )
    html = _sub(course_pattern, html)

    api_pattern = re.compile(
        rf'(?P<prefix>(?:https?://[^"\'\s]+)?/api/v1/courses/){source_course_id}/{resource}/(?P<id>\d+)(?P<tail>[^"\'\s]*)'
    )
    html = _sub(api_pattern, html)

    if include_global:
        global_pattern = re.compile(
            rf'(?P<prefix>(?:https?://[^"\'\s]+)?/(?!courses/)[^"\'\s]*/{resource}/)(?P<id>\d+)(?P<tail>[^"\'\s]*)'
        )

        def _global_repl(match: re.Match[str]) -> str:
            prefix = match.group("prefix")
            old_id = match.group("id")
            tail = match.group("tail") or ""
            new_id = _lookup(old_id)
            if new_id is None:
                return match.group(0)
            return f"{prefix}{new_id}{tail}"

        html = global_pattern.sub(_global_repl, html)

    return html


def rewrite_canvas_links(
    html: str,
    *,
    source_course_id: int,
    target_course_id: int,
    id_map: Dict[str, Dict[Any, Any]],
) -> str:
    if not html:
        return html

    result = html

    files_map = _normalize_numeric_map(id_map.get("files"))
    assignments_map = _normalize_numeric_map(id_map.get("assignments"))
    quizzes_map = _normalize_numeric_map(id_map.get("quizzes"))
    discussions_map = _normalize_numeric_map(id_map.get("discussions"))
    modules_map = _normalize_numeric_map(id_map.get("modules"))
    page_slug_map = id_map.get("pages_url") or {}

    result = _replace_numeric_links(
        result,
        resource="files",
        mapping=files_map,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
        include_global=True,
    )
    result = _replace_numeric_links(
        result,
        resource="assignments",
        mapping=assignments_map,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
    )
    result = _replace_numeric_links(
        result,
        resource="quizzes",
        mapping=quizzes_map,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
    )
    result = _replace_numeric_links(
        result,
        resource="discussion_topics",
        mapping=discussions_map,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
    )
    result = _replace_numeric_links(
        result,
        resource="modules",
        mapping=modules_map,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
    )

    if page_slug_map:
        page_pattern = re.compile(
            rf'(?P<prefix>(?:https?://[^"\'\s]+)?/courses/){source_course_id}/pages/(?P<slug>[\w\-]+)(?P<tail>[^"\'\s]*)'
        )

        def _page_repl(match: re.Match[str]) -> str:
            prefix = match.group("prefix")
            old_slug = match.group("slug")
            tail = match.group("tail") or ""
            new_slug = page_slug_map.get(old_slug)
            if not new_slug:
                return match.group(0)
            return f"{prefix}{target_course_id}/pages/{new_slug}{tail}"

        result = page_pattern.sub(_page_repl, result)

        page_api_pattern = re.compile(
            rf'(?P<prefix>(?:https?://[^"\'\s]+)?/api/v1/courses/){source_course_id}/pages/(?P<slug>[\w\-]+)(?P<tail>[^"\'\s]*)'
        )

        def _page_api_repl(match: re.Match[str]) -> str:
            prefix = match.group("prefix")
            old_slug = match.group("slug")
            tail = match.group("tail") or ""
            new_slug = page_slug_map.get(old_slug)
            if not new_slug:
                return match.group(0)
            return f"{prefix}{target_course_id}/pages/{new_slug}{tail}"

        result = page_api_pattern.sub(_page_api_repl, result)

    return result


def _read_html_candidate(paths: list[Path]) -> Optional[str]:
    for candidate in paths:
        try:
            return candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
    return None


def _postprocess_html_content(
    *,
    canvas: CanvasLike,
    export_root: Path,
    target_course_id: int,
    id_map: Dict[str, Dict[Any, Any]],
) -> None:
    course_meta_path = export_root / "course" / "course_metadata.json"
    source_course_id: Optional[int] = None
    if course_meta_path.exists():
        try:
            meta = json.loads(course_meta_path.read_text(encoding="utf-8"))
            source_course_id = int(meta.get("id")) if meta.get("id") is not None else None
        except Exception:
            source_course_id = None
    if source_course_id is None:
        try:
            source_course_id = int(export_root.name)
        except Exception:
            return

    pages_root = export_root / "pages"
    page_slug_map = id_map.get("pages_url") or {}
    if pages_root.exists():
        for meta_path in pages_root.rglob("page_metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            old_slug = meta.get("url")
            if not isinstance(old_slug, str):
                continue
            new_slug = page_slug_map.get(old_slug) or old_slug

            html_path = meta.get("html_path")
            candidates = []
            if isinstance(html_path, str) and html_path:
                candidates.append(export_root / html_path)
            candidates.append(meta_path.parent / "index.html")
            candidates.append(meta_path.parent / "body.html")

            original_html = _read_html_candidate(candidates)
            if not original_html:
                continue

            rewritten = rewrite_canvas_links(
                original_html,
                source_course_id=source_course_id,
                target_course_id=target_course_id,
                id_map=id_map,
            )
            if rewritten == original_html:
                continue

            try:
                canvas.put(
                    f"/api/v1/courses/{target_course_id}/pages/{new_slug}",
                    json={"wiki_page": {"body": rewritten}},
                )
            except Exception:
                continue

    assignments_root = export_root / "assignments"
    assignment_map = _normalize_numeric_map(id_map.get("assignments"))
    if assignments_root.exists() and assignment_map:
        for meta_path in assignments_root.rglob("assignment_metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            old_id = meta.get("id")
            try:
                old_id_int = int(old_id)
            except (TypeError, ValueError):
                continue
            new_id = assignment_map.get(old_id_int)
            if new_id is None:
                continue

            html_path = meta.get("html_path")
            candidates = []
            if isinstance(html_path, str) and html_path:
                candidates.append(export_root / html_path)
            dir_path = meta_path.parent
            candidates.extend(
                [
                    dir_path / "description.html",
                    dir_path / "index.html",
                    dir_path / "body.html",
                    dir_path / "message.html",
                ]
            )

            original_html = _read_html_candidate(candidates)
            if original_html is None:
                continue

            rewritten = rewrite_canvas_links(
                original_html,
                source_course_id=source_course_id,
                target_course_id=target_course_id,
                id_map=id_map,
            )
            if rewritten == original_html:
                continue

            try:
                canvas.put(
                    f"/api/v1/courses/{target_course_id}/assignments/{new_id}",
                    json={"assignment": {"description": rewritten}},
                )
            except Exception:
                continue
