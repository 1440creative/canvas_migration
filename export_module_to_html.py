#!/usr/bin/env python3
"""
Export a single Canvas module's pages into one combined HTML file and PDF.

Usage:
  python export_module_to_html.py COURSE_ID MODULE_NUMBER
"""
from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from logging_setup import get_logger, setup_logging
from utils.api import source_api, CanvasAPI
from utils.fs import ensure_dir, atomic_write


def _sort_modules(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def m_key(m: Dict[str, Any]):
        pos = m.get("position") if m.get("position") is not None else 999_999
        mid = m.get("id") or 0
        return (pos, mid)

    return sorted(modules, key=m_key)


def _sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def mi_key(i: Dict[str, Any]):
        pos = i.get("position") if i.get("position") is not None else 999_999
        iid = i.get("id") or 0
        return (pos, iid)

    return sorted(items, key=mi_key)


def _render_combined_html(
    *,
    course_id: int,
    module_title: str,
    module_number: int,
    pages: List[Dict[str, str]],
) -> str:
    safe_module_title = html.escape(module_title or f"Module {module_number}")
    title = f"{safe_module_title} (Course {course_id})"

    page_blocks: List[str] = []
    for idx, page in enumerate(pages, start=1):
        page_title = html.escape(page.get("title") or f"Page {idx}")
        body = page.get("body") or ""
        page_blocks.append(
            "\n".join(
                [
                    f'<section class="page-section" data-index="{idx}">',
                    f"  <h2>{page_title}</h2>",
                    '  <div class="page-body">',
                    body,
                    "  </div>",
                    "</section>",
                ]
            )
        )

    if not page_blocks:
        page_blocks.append(
            '<section class="page-section empty"><p>No pages found in this module.</p></section>'
        )

    styles = "\n".join(
        [
            "body { font-family: Georgia, 'Times New Roman', serif; color: #111; line-height: 1.5; }",
            "h1 { font-size: 28px; margin: 0 0 12px 0; }",
            "h2 { font-size: 20px; margin: 24px 0 12px 0; }",
            ".page-section { margin: 0 0 32px 0; }",
            ".page-section + .page-section { page-break-before: always; }",
            ".page-body img { max-width: 100%; height: auto; }",
        ]
    )

    body_html = "\n".join(
        [
            f"<h1>{safe_module_title}</h1>",
            f'<p class="meta">Course {course_id} - Module {module_number}</p>',
            "\n".join(page_blocks),
        ]
    )

    return "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '  <meta charset="utf-8" />',
            f"  <title>{html.escape(title)}</title>",
            f"  <style>{styles}</style>",
            "</head>",
            "<body>",
            body_html,
            "</body>",
            "</html>",
        ]
    )


def _render_pdf(html_path: Path, pdf_path: Path) -> str:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        HTML = None

    tmp_pdf = pdf_path.with_suffix(".tmp.pdf")

    if HTML is not None:
        HTML(filename=str(html_path)).write_pdf(str(tmp_pdf))
        os.replace(tmp_pdf, pdf_path)
        return "weasyprint"

    wkhtml = shutil.which("wkhtmltopdf")
    if wkhtml:
        subprocess.run([wkhtml, str(html_path), str(tmp_pdf)], check=True)
        os.replace(tmp_pdf, pdf_path)
        return "wkhtmltopdf"

    raise RuntimeError(
        "No PDF renderer found. Install weasyprint (pip install weasyprint) "
        "or wkhtmltopdf (brew install wkhtmltopdf)."
    )


def _require_api(api: Optional[CanvasAPI]) -> CanvasAPI:
    if api is None:
        raise ValueError(
            "Canvas API is not configured. Set CANVAS_SOURCE_URL and CANVAS_SOURCE_TOKEN."
        )
    return api


def export_module_to_html(
    course_id: int,
    module_number: int,
    *,
    output_dir: Optional[Path],
    export_root: Path,
    api: CanvasAPI,
) -> Path:
    log = get_logger(artifact="module_export", course_id=course_id)

    log.info("fetching modules", extra={"course_id": course_id})
    modules = api.get(f"/courses/{course_id}/modules")
    if not isinstance(modules, list):
        raise TypeError("Expected list of modules from Canvas API")

    modules_sorted = _sort_modules(modules)
    if module_number < 1 or module_number > len(modules_sorted):
        raise ValueError(f"Module number {module_number} is out of range (1-{len(modules_sorted)}).")

    module = modules_sorted[module_number - 1]
    module_id = int(module["id"])
    module_title = (module.get("name") or f"Module {module_number}").strip()

    log.info(
        "fetching module items",
        extra={"module_id": module_id, "module_number": module_number},
    )
    items = api.get(f"/courses/{course_id}/modules/{module_id}/items")
    if not isinstance(items, list):
        raise TypeError("Expected list of module items from Canvas API")

    items_sorted = _sort_items(items)
    pages: List[Dict[str, str]] = []
    for item in items_sorted:
        if (item.get("type") or "").strip() != "Page":
            continue
        page_url = (item.get("page_url") or "").strip()
        if not page_url:
            continue
        detail = api.get(f"/courses/{course_id}/pages/{page_url}")
        if not isinstance(detail, dict):
            raise TypeError("Expected page detail dict from Canvas API")
        pages.append(
            {
                "title": detail.get("title") or item.get("title") or page_url,
                "body": detail.get("body") or "",
            }
        )

    if output_dir is None:
        output_dir = (
            export_root
            / str(course_id)
            / "module_prints"
            / f"{module_number:03d}_{module_id}"
        )

    ensure_dir(output_dir)
    html_content = _render_combined_html(
        course_id=course_id,
        module_title=module_title,
        module_number=module_number,
        pages=pages,
    )
    html_path = output_dir / "combined.html"
    atomic_write(html_path, html_content)

    log.info("combined html written", extra={"path": str(html_path), "pages": len(pages)})
    return html_path


def main() -> int:
    p = argparse.ArgumentParser(description="Export a module to combined HTML and PDF.")
    p.add_argument("course_id", type=int, help="Canvas course id")
    p.add_argument("module_number", type=int, help="1-based module number (by module position)")
    p.add_argument(
        "--export-root",
        type=Path,
        default=Path("export/data"),
        help="Base export directory (default: export/data)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional explicit output directory (overrides --export-root)",
    )
    p.add_argument(
        "--output-folder",
        type=Path,
        default=None,
        help="Alias for --output-dir (overrides --export-root)",
    )
    p.add_argument("--skip-pdf", action="store_true", help="Only write combined HTML")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    args = p.parse_args()

    setup_logging(verbosity=args.verbose)
    api = _require_api(source_api)

    output_dir = args.output_dir or args.output_folder

    html_path = export_module_to_html(
        course_id=args.course_id,
        module_number=args.module_number,
        output_dir=output_dir,
        export_root=args.export_root,
        api=api,
    )

    if args.skip_pdf:
        return 0

    pdf_path = html_path.with_suffix(".pdf")
    renderer = _render_pdf(html_path, pdf_path)
    log = get_logger(artifact="module_export", course_id=args.course_id)
    log.info("pdf rendered", extra={"path": str(pdf_path), "renderer": renderer})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
