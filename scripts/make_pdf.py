#!/usr/bin/env python3
"""
Build a single US Letter PDF from an exported Canvas course.

Uses the module structure as the backbone, pages in module order.
Images are embedded as base64 data URIs. Supports branded title page,
diagonal watermark, and licence page — same flags as make_epub.py.

Usage:
  python scripts/make_pdf.py --source-dir websites/source/3166
  python scripts/make_pdf.py --source-dir websites/source/3166 --out my.pdf
  python scripts/make_pdf.py --course-dir export/data/target_dump/3166
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import sys
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    load_dotenv(str(REPO_ROOT / ".env.local"), override=True)
except ImportError:
    pass

try:
    import weasyprint
except ImportError:
    sys.exit("weasyprint is required: pip install weasyprint")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("beautifulsoup4 is required: pip install beautifulsoup4")

import requests

DEFAULT_BRAND_DIR = REPO_ROOT / "assets" / "brand"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

PAGE_CSS = """
@page {
    size: letter;
    margin: 1in;
}

body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a1a;
}

h1 { font-size: 18pt; margin-top: 1.2em; margin-bottom: 0.4em; }
h2 { font-size: 15pt; margin-top: 1em;  margin-bottom: 0.3em; }
h3 { font-size: 13pt; margin-top: 0.9em; margin-bottom: 0.3em; }
h4 { font-size: 11pt; font-weight: bold; margin-top: 0.8em; }
h1, h2, h3, h4 { page-break-after: avoid; }

p  { margin: 0.5em 0; orphans: 3; widows: 3; }
a  { color: #2a5db0; }
a:not([href]) { color: #9aaabf; text-decoration: none; cursor: default; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; }

table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #ccc; padding: 0.3em 0.5em; text-align: left; font-size: 10pt; }
th { background: #f0f0f0; font-weight: bold; }

blockquote { border-left: 3px solid #ccc; margin: 1em 0; padding-left: 1em; color: #555; }
pre, code { font-family: 'Courier New', monospace; font-size: 9pt; }
pre { background: #f8f8f8; padding: 0.8em; }

ul, ol { margin: 0.5em 0 0.5em 1.5em; padding: 0; }
li { margin: 0.2em 0; }

.page-break { page-break-before: always; }

.title-page {
    text-align: center;
    padding-top: 2.5in;
    page-break-after: always;
}
.title-page h1 { font-size: 24pt; margin-top: 0.5em; }
.title-page .author { font-size: 13pt; margin-top: 0.8em; color: #444; }
.title-page .institution { font-size: 11pt; margin-top: 2em; color: #888; }
.title-page .tagline { font-size: 11pt; font-style: italic; color: #666; margin-top: 0.3em; }

.toc-page { page-break-after: always; }
.toc-page h1 { margin-bottom: 0.8em; }
.toc-module { font-weight: bold; margin-top: 1em; margin-bottom: 0.2em; }
.toc-page ul { list-style: none; margin: 0 0 0 1em; padding: 0; }
.toc-page li { margin: 0.15em 0; }

.module-header {
    font-size: 9pt;
    font-weight: bold;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #ddd;
    padding-bottom: 0.2em;
    margin-bottom: 0.6em;
}

.chapter { page-break-before: always; }

.licence-page {
    page-break-before: always;
    text-align: center;
    padding-top: 2in;
}
.licence-page img { max-width: 120px; margin: 1em auto; }
"""

WATERMARK_CSS_TMPL = """
body::before {{
    content: "{text}";
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate({rotate_deg}deg);
    font-size: 26pt;
    font-family: Georgia, serif;
    font-weight: bold;
    opacity: {opacity};
    color: {color};
    z-index: -1;
    white-space: nowrap;
    pointer-events: none;
}}
"""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_brand(brand_dir: Path) -> dict:
    try:
        return json.loads((brand_dir / "brand.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_file_id_map(course_dir: Path) -> dict[int, Path]:
    id_map: dict[int, Path] = {}
    files_dir = course_dir / "files"
    if not files_dir.exists():
        return id_map
    for meta_path in files_dir.rglob("*.metadata.json"):
        meta = _read_json(meta_path)
        if not isinstance(meta, dict):
            continue
        fid = meta.get("id")
        if fid is None:
            continue
        candidate = Path(str(meta_path).replace(".metadata.json", ""))
        if candidate.exists() and candidate.is_file():
            id_map[int(fid)] = candidate
    return id_map


def _file_id_from_url(url: str) -> int | None:
    m = re.search(r"/files/(\d+)", url)
    return int(m.group(1)) if m else None


def _fetch_image(url: str, session: requests.Session) -> bytes | None:
    for attempt in range(1, 4):
        try:
            r = session.get(url, timeout=(5, 30))
            if r.status_code == 200:
                return r.content
        except Exception:
            pass
        time.sleep(1.5 * attempt)
    return None


def _data_uri(img_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"


def _clean_filename(name: str) -> str:
    return re.sub(r"^\d+_\d+__", "", name)


# ---------------------------------------------------------------------------
# HTML processing
# ---------------------------------------------------------------------------

def _process_page_html(
    raw_html: str,
    staged: bool,
    staged_images_dir: Path | None,
    file_id_map: dict[int, Path],
    image_cache: dict[str, str],
    session: requests.Session,
    files_base_url: str | None,
) -> str:
    """Return clean body HTML with images as data URIs and file links rewritten."""
    soup = BeautifulSoup(raw_html, "html.parser")

    if staged:
        content = soup
    else:
        content = soup.find("div", class_="main-content") or soup.find("div", class_="ll-master") or soup

    # Remove iframes — cannot render in PDF
    for el in content.find_all("iframe"):
        placeholder = soup.new_tag("p")
        placeholder.string = f"[Interactive content: {el.get('title', 'external tool')}]"
        el.replace_with(placeholder)

    # Embed images as data URIs
    for img in content.find_all("img"):
        src = img.get("src", "")
        if not src:
            img.decompose()
            continue

        if src in image_cache:
            img["src"] = image_cache[src]
            continue

        img_bytes: bytes | None = None
        mime = "image/png"

        if staged and src.startswith("../images/") and staged_images_dir:
            img_path = staged_images_dir / src[len("../images/"):]
            if img_path.exists():
                img_bytes = img_path.read_bytes()
                guessed, _ = mimetypes.guess_type(img_path.name)
                mime = guessed or mime
        else:
            fid = _file_id_from_url(src)
            local_path = file_id_map.get(fid) if fid else None
            if local_path and local_path.exists():
                img_bytes = local_path.read_bytes()
                guessed, _ = mimetypes.guess_type(local_path.name)
                mime = guessed or mime
            else:
                img_bytes = _fetch_image(src, session)
                if img_bytes:
                    guessed, _ = mimetypes.guess_type(src.split("?")[0])
                    mime = guessed or mime

        if not img_bytes:
            img.decompose()
            continue

        data_uri = _data_uri(img_bytes, mime)
        image_cache[src] = data_uri
        img["src"] = data_uri
        for attr in ["data-api-endpoint", "data-api-returntype", "loading", "verifier"]:
            del img[attr]

    # Rewrite or nullify file links
    for a in content.find_all("a", href=True):
        href = a["href"]

        if staged and href.startswith("../files/"):
            import urllib.parse
            filename = href[len("../files/"):]
            if files_base_url:
                a["href"] = files_base_url.rstrip("/") + "/" + urllib.parse.quote(filename, safe="")
            else:
                del a["href"]
            continue

        fid = _file_id_from_url(href)
        if fid:
            local_path = file_id_map.get(fid)
            if local_path and files_base_url:
                import urllib.parse
                clean = _clean_filename(local_path.name)
                a["href"] = files_base_url.rstrip("/") + "/" + urllib.parse.quote(clean, safe="")
            else:
                del a["href"]
            continue

        if "file_contents" in href or "sfu.instructure.com" in href and "/files/" in href:
            if not files_base_url:
                del a["href"]

    return content.decode_contents() if hasattr(content, "decode_contents") else str(content)


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _title_page_html(course_name: str, author: str | None, brand: dict, brand_dir: Path) -> str:
    cfg = brand.get("branding", {})
    institution = cfg.get("institution", "")
    tagline = cfg.get("tagline", "")
    logo_file = cfg.get("logo", "")

    logo_tag = ""
    if logo_file:
        logo_path = brand_dir / logo_file
        if logo_path.exists():
            img_bytes = logo_path.read_bytes()
            guessed, _ = mimetypes.guess_type(logo_path.name)
            mime = guessed or "image/png"
            logo_tag = f'<img src="{_data_uri(img_bytes, mime)}" alt="{institution}" style="max-width:260px; margin:0 auto;"/>'

    author_line = f'<p class="author">{author}</p>' if author else ""
    tagline_line = f'<p class="tagline">{tagline}</p>' if tagline else ""
    inst_line = f'<p class="institution">{institution}</p>' if institution else ""

    return (
        f'<div class="title-page">'
        f'{logo_tag}'
        f'<h1>{course_name}</h1>'
        f'{author_line}'
        f'{tagline_line}'
        f'{inst_line}'
        f'</div>'
    )


def _toc_html(toc_data: list[tuple[str, list[str]]]) -> str:
    rows = ['<div class="toc-page"><h1>Contents</h1>']
    for mod_title, page_titles in toc_data:
        rows.append(f'<p class="toc-module">{mod_title}</p><ul>')
        for title in page_titles:
            rows.append(f'<li>{title}</li>')
        rows.append('</ul>')
    rows.append('</div>')
    return ''.join(rows)


def _licence_html(brand: dict, brand_dir: Path) -> str:
    cfg = brand.get("license", {})
    name = cfg.get("name", "")
    url = cfg.get("url", "")
    statement = cfg.get("statement", "")
    badge_file = cfg.get("badge", "")

    badge_tag = ""
    if badge_file:
        badge_path = brand_dir / badge_file
        if badge_path.exists():
            img_bytes = badge_path.read_bytes()
            guessed, _ = mimetypes.guess_type(badge_path.name)
            mime = guessed or "image/png"
            badge_tag = f'<img src="{_data_uri(img_bytes, mime)}" alt="{name}"/>'

    return (
        f'<div class="licence-page">'
        f'<h2>Licence</h2>'
        f'<p>{statement}</p>'
        f'<p><a href="{url}">{name}</a></p>'
        f'{badge_tag}'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_pdf(
    course_dir: Path | None,
    out_path: Path,
    source_dir: Path | None = None,
    title_override: str | None = None,
    author: str | None = None,
    files_base_url: str | None = None,
    branded: bool = False,
    watermark: bool = False,
    licensed: bool = False,
    brand_dir: Path | None = None,
) -> None:
    t0 = time.perf_counter()

    staged = source_dir is not None

    if staged:
        meta: dict = _read_json(source_dir / "course_metadata.json") or {}
        modules_data: list = _read_json(source_dir / "modules.json") or []
        staged_pages_dir = source_dir / "pages"
        staged_images_dir = source_dir / "images"
        slug_set: set[str] = {f.stem for f in staged_pages_dir.glob("*.html")}
        file_id_map: dict[int, Path] = {}
    else:
        meta = _read_json(course_dir / "course" / "course_metadata.json") or {}
        modules_data = _read_json(course_dir / "modules" / "modules.json") or []
        file_id_map = _build_file_id_map(course_dir)
        pages_dir = course_dir / "pages"
        slug_map: dict[str, Path] = {}
        if pages_dir.exists():
            for page_dir in pages_dir.iterdir():
                if page_dir.is_dir():
                    slug = re.sub(r"^\d+_", "", page_dir.name)
                    slug_map[slug] = page_dir
        staged_pages_dir = staged_images_dir = None

    course_name = title_override or meta.get("name") or (source_dir or course_dir).name

    if not modules_data:
        sys.exit("No modules found")

    import os
    session = requests.Session()
    token = os.getenv("CANVAS_TARGET_TOKEN") or os.getenv("CANVAS_SOURCE_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    resolved_brand_dir = brand_dir or DEFAULT_BRAND_DIR
    brand = _load_brand(resolved_brand_dir) if (branded or watermark or licensed) else {}

    # Build CSS
    css = PAGE_CSS
    if watermark:
        wm = brand.get("watermark", {})
        css += WATERMARK_CSS_TMPL.format(
            text=wm.get("text", "For personal use only"),
            opacity=wm.get("opacity", 0.08),
            color=wm.get("color", "#888888"),
            rotate_deg=wm.get("rotate_deg", -35),
        )

    # Assemble document sections
    sections: list[str] = []
    image_cache: dict[str, str] = {}
    toc_data: list[tuple[str, list[str]]] = []
    page_count = 0

    if branded:
        sections.append(_title_page_html(course_name, author, brand, resolved_brand_dir))

    # Placeholder — TOC inserted after we know page titles
    toc_placeholder = f"<!-- TOC -->"
    sections.append(toc_placeholder)

    first_chapter = True
    for mod in modules_data:
        if mod.get("published") is False:
            continue
        mod_title = mod.get("name") or f"Module {mod.get('position', '')}"
        mod_page_titles: list[str] = []

        for item in mod.get("items", []):
            if item.get("type") != "Page":
                continue
            slug = item.get("page_url") or ""
            title = (item.get("title") or "").strip()
            if not slug or not title:
                continue

            if staged:
                if slug not in slug_set:
                    continue
                raw_html = (staged_pages_dir / f"{slug}.html").read_text(encoding="utf-8")
            else:
                page_dir = slug_map.get(slug)
                if not page_dir:
                    continue
                html_path = page_dir / "index.html"
                if not html_path.exists():
                    continue
                raw_html = html_path.read_text(encoding="utf-8")

            body = _process_page_html(
                raw_html, staged, staged_images_dir, file_id_map,
                image_cache, session, files_base_url,
            )

            break_class = "" if first_chapter else ' class="chapter page-break"'
            first_chapter = False

            sections.append(
                f'<div{break_class}>'
                f'<p class="module-header">{mod_title}</p>'
                f'<h1>{title}</h1>'
                f'{body}'
                f'</div>'
            )
            mod_page_titles.append(title)
            page_count += 1

        if mod_page_titles:
            toc_data.append((mod_title, mod_page_titles))

    if licensed:
        sections.append(_licence_html(brand, resolved_brand_dir))

    # Replace TOC placeholder
    toc_section = _toc_html(toc_data)
    html_body = '\n'.join(sections).replace(toc_placeholder, toc_section)

    full_html = (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8"/>'
        f'<title>{course_name}</title>'
        f'<style>{css}</style>'
        '</head><body>'
        f'{html_body}'
        '</body></html>'
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=full_html).write_pdf(str(out_path))

    elapsed = time.perf_counter() - t0
    print(f"\n  Course:   {course_name}")
    print(f"  Pages:    {page_count}")
    print(f"  Images:   {len(image_cache)}")
    if files_base_url:
        print(f"  Files URL: {files_base_url}")
    print(f"  Output:   {out_path}")
    print(f"  Time:     {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Build a PDF from an exported Canvas course")
    p.add_argument("--course-dir", type=Path, default=None,
                   help="Raw Canvas dump directory (required if --source-dir not given)")
    p.add_argument("--source-dir", type=Path, default=None,
                   help="Staged editable source (from stage_site.py). Use instead of --course-dir.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output PDF path (default: <source-dir>/<id>.pdf)")
    p.add_argument("--title", default=None, help="Override the course title")
    p.add_argument("--author", default=None, help="Author/publisher metadata and title page")
    p.add_argument("--files-base-url", default=None,
                   help="Base URL for hosted files. Canvas file links rewritten here; omit to nullify them.")
    p.add_argument("--branded", action="store_true",
                   help="Insert a branded title page at the front (uses assets/brand/brand.json).")
    p.add_argument("--watermark", action="store_true",
                   help="Overlay a diagonal watermark on every page.")
    p.add_argument("--licensed", action="store_true",
                   help="Append a licence page at the back.")
    p.add_argument("--brand-dir", type=Path, default=None,
                   help="Path to brand assets folder (default: assets/brand/).")
    args = p.parse_args()

    if not args.course_dir and not args.source_dir:
        p.error("one of --course-dir or --source-dir is required")
    if args.course_dir and args.source_dir:
        p.error("--course-dir and --source-dir are mutually exclusive")

    if args.source_dir:
        source_dir = args.source_dir.resolve()
        if not source_dir.is_dir():
            p.error(f"Source directory not found: {source_dir}")
        course_dir = None
        out_path = args.out or (source_dir / f"{source_dir.name}.pdf")
        label = source_dir.name
    else:
        course_dir = args.course_dir.resolve()
        if not course_dir.is_dir():
            p.error(f"Course directory not found: {course_dir}")
        source_dir = None
        out_path = args.out or (course_dir / f"{course_dir.name}.pdf")
        label = course_dir.name

    if args.out:
        out_path = args.out
        if out_path.suffix.lower() != ".pdf":
            out_path = out_path / f"{label}.pdf"

    print(f"Building PDF for {label}...")
    build_pdf(
        course_dir, out_path,
        source_dir=source_dir,
        title_override=args.title,
        author=args.author,
        files_base_url=args.files_base_url,
        branded=args.branded,
        watermark=args.watermark,
        licensed=args.licensed,
        brand_dir=args.brand_dir.resolve() if args.brand_dir else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
