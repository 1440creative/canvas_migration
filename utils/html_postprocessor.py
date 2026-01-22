"""Utilities for rewriting Canvas links in exported HTML using id_map mappings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

from importers.import_course import rewrite_canvas_links


@dataclass
class HtmlPostprocessReport:
    """Summary of HTML rewrites performed during post-processing."""

    rewritten_files: List[Path]
    skipped_files: List[Path]

    @property
    def total_files(self) -> int:
        return len(self.rewritten_files) + len(self.skipped_files)

    @property
    def rewrites_applied(self) -> int:
        return len(self.rewritten_files)


class MissingSourceCourseIdError(RuntimeError):
    """Raised when the source course identifier cannot be determined."""


def _resolve_source_course_id(export_root: Path, explicit: Optional[int]) -> int:
    if explicit is not None:
        return explicit

    course_meta_path = export_root / "course" / "course_metadata.json"
    if course_meta_path.exists():
        try:
            meta = json.loads(course_meta_path.read_text(encoding="utf-8"))
            maybe_id = meta.get("id")
            if maybe_id is not None:
                return int(maybe_id)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    try:
        return int(export_root.name)
    except ValueError as exc:
        raise MissingSourceCourseIdError(
            "Unable to determine source course id; pass --source-course-id explicitly."
        ) from exc


def _html_candidates(export_root: Path) -> Iterable[Path]:
    for path in export_root.rglob("*.html"):
        if path.is_file():
            yield path


def _serialize_html_fragment(soup: BeautifulSoup) -> str:
    """
    Serialize soup without adding <html>/<body> wrappers for fragments.
    """
    if soup.body:
        return "".join(str(child) for child in soup.body.contents)
    return str(soup)


def replace_anchor_href(
    html: str,
    *,
    target_href: str,
    replacement_href: str,
) -> Tuple[str, int]:
    """
    Replace exact-match <a href="..."> links and return (new_html, replacements).
    """
    if not html or target_href == replacement_href:
        return html, 0

    soup = BeautifulSoup(html, "html.parser")
    changed = 0
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if href == target_href:
            anchor["href"] = replacement_href
            changed += 1

    if changed == 0:
        return html, 0

    return _serialize_html_fragment(soup), changed


def postprocess_html(
    *,
    export_root: Path,
    target_course_id: int,
    id_map: Dict[str, Dict[Any, Any]],
    source_course_id: Optional[int] = None,
    dry_run: bool = False,
    extra_paths: Optional[Iterable[Path]] = None,
) -> HtmlPostprocessReport:
    """Rewrite Canvas resource links in exported HTML files.

    Args:
        export_root: Base directory containing exported Canvas artifacts.
        target_course_id: Canvas course id that now owns the imported content.
        id_map: Mapping produced during import that records old -> new ids.
        source_course_id: Optional explicit source course id override.
        dry_run: When True, report rewrites without writing any files.
        extra_paths: Optional iterable of additional HTML paths to include.

    Returns:
        HtmlPostprocessReport summarizing which files were updated.
    """

    resolved_source = _resolve_source_course_id(export_root, source_course_id)

    # Build a deterministic list so tests have stable ordering.
    seen: set[Path] = set()
    html_paths: List[Path] = []

    for html_path in _html_candidates(export_root):
        if html_path not in seen:
            seen.add(html_path)
            html_paths.append(html_path)

    if extra_paths:
        for path in extra_paths:
            if path.is_file() and path not in seen:
                seen.add(path)
                html_paths.append(path)

    html_paths.sort()

    rewritten: List[Path] = []
    skipped: List[Path] = []

    for html_path in html_paths:
        try:
            original_html = html_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped.append(html_path)
            continue

        updated_html = rewrite_canvas_links(
            original_html,
            source_course_id=resolved_source,
            target_course_id=target_course_id,
            id_map=id_map,
        )

        if updated_html == original_html:
            skipped.append(html_path)
            continue

        if not dry_run:
            html_path.write_text(updated_html, encoding="utf-8")

        rewritten.append(html_path)

    return HtmlPostprocessReport(rewritten_files=rewritten, skipped_files=skipped)


__all__ = [
    "HtmlPostprocessReport",
    "MissingSourceCourseIdError",
    "postprocess_html",
    "replace_anchor_href",
]
