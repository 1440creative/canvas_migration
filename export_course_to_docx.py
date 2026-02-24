#!/usr/bin/env python3
"""
Export a Canvas course (cloud/TARGET server) to a single Word (.docx) document.

Usage:
  python export_course_to_docx.py COURSE_ID [--output OUTPUT_DIR]

Content included (in module order):
  - Pages
  - Assignment descriptions (non-quiz)
  - Discussion prompts (deduplicated)
  - SubHeaders as visual dividers

iframe handling:
  - lll-web01 self-tests  → fetched, inputs replaced with correct answers, inlined
  - Canvas media embeds   → [Video] placeholder
  - YouTube embeds        → [Video: URL] placeholder
  - H5P interactive       → [Interactive content] placeholder

Images:
  - Downloaded from Canvas with auth token to local assets dir
  - src rewritten to local paths before pandoc conversion

Requires:
  - pandoc >= 2.x (brew install pandoc)
  - pip install requests beautifulsoup4 python-dotenv
  - CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in .env.local
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup, Tag

# --- repo root on sys.path ---
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env.local", override=True)

from utils.api import CanvasAPI
from logging_setup import get_logger, setup_logging

setup_logging()
log = get_logger(artifact="docx_export", course_id=0)  # course_id set after arg parse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

QUIZ_BOILERPLATE_MAX_LEN = 300  # assignment descriptions shorter than this + quiz-named are skipped
ENGAGEMENT_ASSESSMENT_PATTERN = re.compile(r"engagement assessment", re.I)
QUIZ_NAME_PATTERN = re.compile(r"^quiz\s+\d+$", re.I)


def _api() -> CanvasAPI:
    url = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not url or not token:
        sys.exit("ERROR: CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in .env.local")
    return CanvasAPI(url, token)


def _download_image(src: str, assets_dir: Path, token: str) -> Optional[Path]:
    """Download a Canvas-hosted image using auth token. Returns local path or None on failure."""
    try:
        parsed = urllib.parse.urlparse(src)
        # Derive a safe filename from the URL path
        url_path = parsed.path.lstrip("/")
        safe_name = re.sub(r"[^\w.\-]", "_", url_path)[-120:]  # truncate
        local_path = assets_dir / safe_name
        if local_path.exists():
            return local_path
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(src, headers=headers, timeout=30)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)
        return local_path
    except Exception as e:
        log.warning(f"Failed to download image {src}: {e}")
        return None


def _fetch_lll_web01(src: str) -> Optional[str]:
    """
    Fetch a lll-web01 self-test page and return cleaned HTML string.
    - Removes scripts, styles, nav, toolbar, message divs
    - Replaces <input data-correct-entry="X"> with the correct answer text
    """
    try:
        resp = requests.get(src, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"Failed to fetch lll-web01 iframe {src}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "link", "meta", "nav", "header", "footer",
                     "noscript"]):
        tag.decompose()
    for sel in [".toolbar", ".message", "#revealSolution", "#resetPuzzle"]:
        for el in soup.select(sel):
            el.decompose()

    # Replace interactive inputs with their correct answers
    for inp in soup.find_all("input", attrs={"data-correct-entry": True}):
        answer = inp.get("data-correct-entry", "?")
        replacement = soup.new_tag("span")
        replacement["class"] = "self-test-answer"
        replacement.string = answer
        inp.replace_with(replacement)

    # Any remaining inputs → placeholder
    for inp in soup.find_all("input"):
        replacement = soup.new_tag("span")
        replacement.string = "___"
        inp.replace_with(replacement)

    body = soup.find("body")
    if body:
        return str(body)
    return str(soup)


def _iframe_placeholder(src: str, kind: str) -> str:
    """Return a styled HTML placeholder block for a non-inlineable iframe."""
    safe_src = src.replace("&amp;", "&")
    if kind == "youtube":
        label = f'Video (YouTube): <a href="{safe_src}">{safe_src}</a>'
    elif kind == "canvas_media":
        label = "Embedded video (Canvas media player)"
    elif kind == "h5p":
        label = f'Interactive content (H5P): <a href="{safe_src}">{safe_src}</a>'
    else:
        label = f'Embedded content: <a href="{safe_src}">{safe_src}</a>'
    return f'<div class="iframe-placeholder"><p><em>[{label}]</em></p></div>'


def _classify_iframe(src: str) -> str:
    if "youtube.com/embed" in src or "youtu.be" in src:
        return "youtube"
    if "media_attachments_iframe" in src:
        return "canvas_media"
    if "h5p" in src:
        return "h5p"
    if "lll-web01.its.sfu.ca" in src:
        return "lll_web01"
    return "other"


def preprocess_html(
    html_body: str,
    assets_dir: Path,
    token: str,
    canvas_base_url: str,
) -> str:
    """
    Clean and transform a Canvas HTML body for pandoc conversion:
    - Strip ll-master/main-content wrapper divs (keep children)
    - Download Canvas images, rewrite src to local paths
    - Inline lll-web01 iframe content
    - Replace other iframes with placeholders
    """
    if not html_body or not html_body.strip():
        return ""

    soup = BeautifulSoup(html_body, "html.parser")

    # Unwrap Canvas layout divs (ll-master, main-content) — keep their children
    for cls in ["ll-master", "main-content"]:
        for wrapper in soup.find_all(class_=cls):
            wrapper.unwrap()

    # --- Images ---
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        # Resolve relative URLs
        if src.startswith("/"):
            src = canvas_base_url.rstrip("/") + src
        if canvas_base_url.split("//")[1].split("/")[0] in src or "instructure.com" in src:
            local = _download_image(src, assets_dir, token)
            if local:
                img["src"] = str(local)
        # External images: leave src as-is (pandoc will try to fetch or skip)

    # --- iframes ---
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "").replace("&amp;", "&")
        if not src:
            iframe.decompose()
            continue

        kind = _classify_iframe(src)

        if kind == "lll_web01":
            content = _fetch_lll_web01(src)
            if content:
                # Wrap in a div with a note
                wrapper = soup.new_tag("div", attrs={"class": "self-test-inline"})
                note = soup.new_tag("p")
                em = soup.new_tag("em")
                em.string = "[Self-test (answers shown)]"
                note.append(em)
                wrapper.append(note)
                inner = BeautifulSoup(content, "html.parser")
                wrapper.append(inner)
                iframe.replace_with(wrapper)
            else:
                placeholder = BeautifulSoup(
                    _iframe_placeholder(src, "other"), "html.parser"
                )
                iframe.replace_with(placeholder)
        else:
            placeholder = BeautifulSoup(_iframe_placeholder(src, kind), "html.parser")
            iframe.replace_with(placeholder)

    # Remove Canvas-specific data attributes to keep HTML clean
    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            if attr.startswith("data-") and attr not in ("data-correct-entry",):
                del tag[attr]

    return str(soup)


# ---------------------------------------------------------------------------
# Content fetching
# ---------------------------------------------------------------------------

def fetch_modules_with_items(course_id: int, api: CanvasAPI) -> List[Dict[str, Any]]:
    modules = api.get(f"courses/{course_id}/modules", params={"per_page": 100, "include[]": "items"})
    if not isinstance(modules, list):
        raise TypeError("Expected list of modules")

    def m_key(m: Dict) -> tuple:
        return (m.get("position") or 999_999, m.get("id") or 0)

    return sorted(modules, key=m_key)


def fetch_page_body(course_id: int, page_url: str, api: CanvasAPI) -> tuple[str, str]:
    """Returns (title, html_body)."""
    detail = api.get(f"courses/{course_id}/pages/{page_url}")
    return detail.get("title") or "", detail.get("body") or ""


def fetch_assignment_body(course_id: int, assignment_id: int, api: CanvasAPI) -> tuple[str, str]:
    """Returns (title, html_body)."""
    detail = api.get(f"courses/{course_id}/assignments/{assignment_id}")
    return detail.get("name") or "", detail.get("description") or ""


def fetch_discussion_body(course_id: int, discussion_id: int, api: CanvasAPI) -> tuple[str, str]:
    """Returns (title, html_body)."""
    detail = api.get(f"courses/{course_id}/discussion_topics/{discussion_id}")
    return detail.get("title") or "", detail.get("message") or ""


def _is_quiz_assignment(item: Dict[str, Any]) -> bool:
    title = item.get("title") or ""
    return bool(QUIZ_NAME_PATTERN.match(title.strip()))


def _is_boring_assignment(title: str, body: str) -> bool:
    """Skip quiz-boilerplate assignments with essentially no content."""
    if QUIZ_NAME_PATTERN.match(title.strip()):
        return True
    if len(body.strip()) < QUIZ_BOILERPLATE_MAX_LEN and "quiz" in title.lower():
        return True
    return False


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

STYLES = """
body {
  font-family: Calibri, 'Segoe UI', Arial, sans-serif;
  font-size: 11pt;
  color: #111;
  line-height: 1.5;
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}
h1 { font-size: 22pt; margin: 36px 0 6px 0; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 16pt; margin: 24px 0 6px 0; }
h2.item-title { border-bottom: 1px solid #ccc; padding-bottom: 4px; }
h3 { font-size: 13pt; margin: 18px 0 4px 0; }
h4 { font-size: 11pt; margin: 14px 0 4px 0; }
p  { margin: 6px 0 10px 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  font-size: 10pt;
}
th, td {
  border: 1px solid #aaa;
  padding: 4px 8px;
  vertical-align: top;
}
th, .title { font-weight: bold; }
.currency { text-align: right; }
.subtitle { font-style: italic; }
.self-test-inline { margin: 12px 0; padding: 8px; background: #f8f8f8; border-left: 3px solid #999; }
.self-test-answer { font-weight: bold; }
.iframe-placeholder { margin: 10px 0; padding: 8px; background: #f0f0f0; border: 1px dashed #aaa; }
.item-type-label { font-size: 9pt; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
hr.subheader { border: none; border-top: 1px solid #ddd; margin: 20px 0; }
""".strip()


def build_combined_html(
    course_id: int,
    course_name: str,
    modules: List[Dict[str, Any]],
    api: CanvasAPI,
    assets_dir: Path,
    token: str,
    canvas_base_url: str,
) -> str:
    seen_discussion_ids: Set[int] = set()
    seen_assignment_ids: Set[int] = set()

    sections: List[str] = []

    for module in modules:
        module_title = module.get("name") or f"Module {module.get('position', '?')}"
        items = module.get("items") or []

        log.info(f"Processing module: {module_title} ({len(items)} items)")

        # Sort items by position
        items_sorted = sorted(items, key=lambda i: (i.get("position") or 999_999, i.get("id") or 0))

        module_blocks: List[str] = []

        for item in items_sorted:
            item_type = item.get("type", "")
            item_title = item.get("title") or ""
            content_id = item.get("content_id")

            if item_type == "SubHeader":
                module_blocks.append(
                    f'<hr class="subheader"><h3 class="subheader-label">{item_title}</h3>'
                )
                continue

            if item_type == "Page":
                page_url = item.get("page_url") or item.get("url") or ""
                if not page_url:
                    continue
                title, body = fetch_page_body(course_id, page_url, api)
                if not body.strip():
                    continue
                processed = preprocess_html(body, assets_dir, token, canvas_base_url)
                module_blocks.append(
                    f'<h2 class="item-title">{title}</h2>\n'
                    f'<div class="item-body">{processed}</div>'
                )

            elif item_type == "Discussion":
                disc_id = content_id
                if not disc_id or disc_id in seen_discussion_ids:
                    continue
                seen_discussion_ids.add(disc_id)
                title, body = fetch_discussion_body(course_id, disc_id, api)
                if not body.strip():
                    continue
                processed = preprocess_html(body, assets_dir, token, canvas_base_url)
                module_blocks.append(
                    f'<p class="item-type-label">Discussion</p>'
                    f'<h2 class="item-title">{title}</h2>\n'
                    f'<div class="item-body">{processed}</div>'
                )

            elif item_type == "Assignment":
                assign_id = content_id
                if not assign_id or assign_id in seen_assignment_ids:
                    continue
                if _is_quiz_assignment(item):
                    continue
                title, body = fetch_assignment_body(course_id, assign_id, api)
                if _is_boring_assignment(title, body):
                    continue
                # Skip engagement assessments — covered as Discussion items
                if ENGAGEMENT_ASSESSMENT_PATTERN.search(title):
                    seen_assignment_ids.add(assign_id)
                    continue
                seen_assignment_ids.add(assign_id)
                if not body.strip():
                    continue
                processed = preprocess_html(body, assets_dir, token, canvas_base_url)
                module_blocks.append(
                    f'<p class="item-type-label">Assignment</p>'
                    f'<h2 class="item-title">{title}</h2>\n'
                    f'<div class="item-body">{processed}</div>'
                )

            elif item_type in ("Quiz", "File", "ExternalUrl", "ExternalTool"):
                # Skip — not prose content
                continue

        if module_blocks:
            sections.append(
                f'<section class="module">\n'
                f'<h1>{module_title}</h1>\n'
                + "\n\n".join(module_blocks)
                + "\n</section>"
            )

    doc_title = f"{course_name} (Course {course_id})"
    body_html = "\n\n".join(sections)

    return "\n".join([
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8" />',
        f"  <title>{doc_title}</title>",
        f"  <style>{STYLES}</style>",
        "</head>",
        "<body>",
        f'<h1 class="doc-title" style="page-break-before:avoid">{doc_title}</h1>',
        body_html,
        "</body>",
        "</html>",
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Export Canvas course to Word (.docx)")
    parser.add_argument("course_id", type=int, help="Canvas course ID (from TARGET/cloud server)")
    parser.add_argument(
        "--output", "-o",
        default=str(REPO_ROOT / "export" / "docx"),
        help="Output directory (default: export/docx/)",
    )
    args = parser.parse_args()

    course_id: int = args.course_id
    output_root = Path(args.output)
    course_out = output_root / str(course_id)
    assets_dir = course_out / "assets"
    course_out.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(exist_ok=True)

    api = _api()
    token = os.getenv("CANVAS_TARGET_TOKEN", "")
    canvas_base_url = os.getenv("CANVAS_TARGET_URL", "").rstrip("/")

    global log
    log = get_logger(artifact="docx_export", course_id=course_id)

    # Fetch course name
    course_info = api.get(f"courses/{course_id}")
    course_name = course_info.get("name") or f"Course {course_id}"
    log.info(f"Exporting course: {course_name} ({course_id})")

    # Fetch modules + items
    modules = fetch_modules_with_items(course_id, api)
    log.info(f"Found {len(modules)} modules")

    # Build combined HTML
    html = build_combined_html(
        course_id=course_id,
        course_name=course_name,
        modules=modules,
        api=api,
        assets_dir=assets_dir,
        token=token,
        canvas_base_url=canvas_base_url,
    )

    # Write HTML (useful for debugging)
    html_path = course_out / f"course_{course_id}.html"
    html_path.write_text(html, encoding="utf-8")
    log.info(f"HTML written to {html_path}")

    # Convert to docx with pandoc
    docx_path = course_out / f"course_{course_id}.docx"
    pandoc_cmd = [
        "pandoc",
        str(html_path),
        "--from", "html",
        "--to", "docx",
        "--output", str(docx_path),
        "--standalone",
        f"--resource-path={assets_dir}",
    ]
    log.info(f"Running pandoc: {' '.join(pandoc_cmd)}")
    result = subprocess.run(pandoc_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: pandoc failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    if result.stderr:
        print(f"pandoc warnings:\n{result.stderr}")

    print(f"\nDone.")
    print(f"  HTML: {html_path}")
    print(f"  DOCX: {docx_path}")
    print(f"  Assets: {assets_dir} ({len(list(assets_dir.iterdir()))} files)")


if __name__ == "__main__":
    main()
