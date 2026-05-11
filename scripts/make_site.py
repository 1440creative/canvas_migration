#!/usr/bin/env python3
"""
Build a static HTML site from an exported Canvas course.

Module structure drives the sidebar TOC (collapsible accordion).
Only Page items are included — quizzes, discussions, assignments omitted.
Each page gets Prev/Next navigation. Images resolved from local files first,
fetched from Canvas if missing.

Usage:
  python scripts/make_site.py --course-dir export/data/target_dump/3001
  python scripts/make_site.py --course-dir export/data/target_dump/3001 --out export/data/target_dump/3001/site
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
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
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("beautifulsoup4 is required: pip install beautifulsoup4")

import requests

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

CSS = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 16px;
    line-height: 1.65;
    color: #1a1a1a;
    display: flex;
    min-height: 100vh;
}

/* ── Sidebar ── SFU brand: #A6192E dark red, #CC0633 light red */
#sidebar {
    width: 280px;
    min-width: 280px;
    background: #A6192E;
    color: #f5e6e9;
    display: flex;
    flex-direction: column;
    position: fixed;
    top: 0; left: 0; bottom: 0;
    overflow-y: auto;
    z-index: 100;
}

#sidebar-logo {
    padding: 1rem 1rem 0.6rem;
    background: #ffffff;
    text-align: left;
    border-right: 1px solid #8c1020;
}

#sidebar-logo img {
    height: auto;
    width: auto;
    display: block;
    border-radius: 0;
}

#sidebar-header {
    padding: 0.6rem 1rem 1rem;
    background: #8C1020;
    font-size: 0.78rem;
    font-family: system-ui, sans-serif;
    color: rgba(255,255,255,0.65);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-bottom: 1px solid rgba(0,0,0,0.25);
}

#sidebar-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: #fff;
    margin-top: 0.3rem;
    text-transform: none;
    letter-spacing: 0;
    line-height: 1.3;
}

.module {
    border-bottom: 1px solid rgba(0,0,0,0.2);
}

.module-toggle {
    width: 100%;
    background: none;
    border: none;
    color: rgba(255,255,255,0.85);
    font-family: system-ui, sans-serif;
    font-size: 0.82rem;
    font-weight: 600;
    text-align: left;
    padding: 0.75rem 1rem;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    letter-spacing: 0.02em;
}

.module-toggle:hover { background: rgba(0,0,0,0.2); color: #fff; }

.module-toggle .arrow {
    transition: transform 0.2s;
    font-size: 0.65rem;
    opacity: 0.6;
}

.module.open .module-toggle .arrow { transform: rotate(90deg); }

.module-pages {
    display: none;
    list-style: none;
    padding: 0.25rem 0;
    background: rgba(0,0,0,0.18);
}

.module.open .module-pages { display: block; }

.module-pages li a {
    display: block;
    padding: 0.45rem 1rem 0.45rem 1.4rem;
    color: rgba(255,255,255,0.7);
    text-decoration: none;
    font-family: system-ui, sans-serif;
    font-size: 0.8rem;
    line-height: 1.35;
    border-left: 3px solid transparent;
}

.module-pages li a:hover {
    color: #fff;
    background: rgba(0,0,0,0.15);
    border-left-color: #CC0633;
}

/* ── Main content ── */
#main {
    margin-left: 280px;
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
}

#content {
    flex: 1;
    max-width: 820px;
    width: 100%;
    margin: 0 auto;
    padding: 2.5rem 2rem;
}

h1 { font-size: 1.7rem; margin-bottom: 1.2rem; line-height: 1.25; color: #111; }
h2 { font-size: 1.3rem; margin: 1.4rem 0 0.6rem; }
h3 { font-size: 1.1rem; margin: 1.1rem 0 0.4rem; }
h4, h5 { font-size: 1rem; margin: 0.9rem 0 0.3rem; }
p  { margin: 0.7rem 0; }
ul, ol { margin: 0.7rem 0 0.7rem 1.6rem; }
li { margin: 0.25rem 0; }
a  { color: #CC0633; }
a:hover { color: #A6192E; }
img { max-width: 100%; height: auto; display: block; margin: 1rem auto; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.95rem; }
th, td { border: 1px solid #d1d5db; padding: 0.5rem 0.75rem; text-align: left; }
th { background: #f3f4f6; font-weight: 600; }
blockquote { border-left: 4px solid #d1d5db; padding-left: 1rem; color: #6b7280; margin: 1rem 0; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 1rem; overflow-x: auto; font-size: 0.88rem; }
code { font-family: 'Courier New', monospace; font-size: 0.9em; background: #f1f5f9; padding: 0.1em 0.3em; border-radius: 3px; }
pre code { background: none; padding: 0; }

/* ── Prev/Next ── */
#page-nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e5e7eb;
    gap: 1rem;
}

.nav-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.6rem 1.1rem;
    background: #CC0633;
    color: #fff;
    text-decoration: none;
    border-radius: 6px;
    font-family: system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 500;
    transition: background 0.15s;
}

.nav-btn:hover { background: #A6192E; color: #fff; }
.nav-btn.disabled { opacity: 0.3; pointer-events: none; }
.nav-btn-label { font-size: 0.75rem; color: rgba(255,255,255,0.75); display: block; }

.nav-btn-prev .nav-btn-label { text-align: left; }
.nav-btn-next .nav-btn-label { text-align: right; }

#page-nav-center {
    font-family: system-ui, sans-serif;
    font-size: 0.78rem;
    color: #9ca3af;
    text-align: center;
    flex: 1;
}
"""

NAV_JS = """\
document.querySelectorAll('.module-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
        btn.closest('.module').classList.toggle('open');
    });
});
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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


def _copy_image(src_path: Path, images_dir: Path) -> str:
    content_hash = hashlib.md5(src_path.read_bytes()).hexdigest()[:12]
    ext = src_path.suffix or ".bin"
    dest_name = f"{content_hash}{ext}"
    dest = images_dir / dest_name
    if not dest.exists():
        dest.write_bytes(src_path.read_bytes())
    return f"../images/{dest_name}"


def _fetch_and_copy_image(url: str, images_dir: Path,
                          session: requests.Session) -> str | None:
    content_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    ext = Path(url.split("?")[0]).suffix or ".png"
    dest_name = f"{content_hash}{ext}"
    dest = images_dir / dest_name
    if not dest.exists():
        data = _fetch_image(url, session)
        if not data:
            return None
        dest.write_bytes(data)
    return f"../images/{dest_name}"


def _clean_filename(name: str) -> str:
    # Strip leading Canvas timestamp/id prefix: e.g. "1644356533_374__foo.pdf" → "foo.pdf"
    return re.sub(r"^\d+_\d+__", "", name)


def _copy_local_file(src_path: Path, files_dir: Path) -> str:
    clean = _clean_filename(src_path.name)
    dest = files_dir / clean
    if dest.exists() and dest.read_bytes() == src_path.read_bytes():
        return f"../files/{clean}"
    # Avoid collision: prefix with file id from filename if dest is already taken by different content
    if dest.exists():
        prefix = re.match(r"^(\d+_\d+)__", src_path.name)
        clean = f"{prefix.group(1)}__{clean}" if prefix else src_path.name
        dest = files_dir / clean
    if not dest.exists():
        dest.write_bytes(src_path.read_bytes())
    return f"../files/{clean}"


def _slug_to_filename(slug: str) -> str:
    return f"{slug}.html"


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# HTML processing
# ---------------------------------------------------------------------------

def _process_html(raw_html: str, file_id_map: dict[int, Path],
                  images_dir: Path, files_dir: Path,
                  session: requests.Session,
                  slug_map: dict[str, str]) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    content = (soup.find("div", class_="main-content")
                or soup.find("div", class_="ll-master")
                or soup)

    for img in content.find_all("img"):
        src = img.get("src", "")
        if not src:
            img.decompose()
            continue

        new_src = None
        fid = _file_id_from_url(src)
        local_path = file_id_map.get(fid) if fid else None

        if local_path and local_path.exists():
            new_src = _copy_image(local_path, images_dir)
        else:
            new_src = _fetch_and_copy_image(src, images_dir, session)

        if new_src:
            img["src"] = new_src
        else:
            img.decompose()

        if img.attrs:
            for attr in ["data-api-endpoint", "data-api-returntype", "loading", "verifier"]:
                img.attrs.pop(attr, None)

    # Rewrite internal Canvas page/file links to local paths
    for a in content.find_all("a", href=True):
        href = a["href"]

        # Internal page links → local .html
        m = re.search(r"/pages/([^/?#]+)", href)
        if m:
            target_slug = m.group(1)
            if target_slug in slug_map:
                a["href"] = f"../{slug_map[target_slug]}"
            continue

        # Canvas file links → local copy
        fid = _file_id_from_url(href)
        if fid:
            local_path = file_id_map.get(fid)
            if local_path and local_path.exists():
                a["href"] = _copy_local_file(local_path, files_dir)
                a.attrs.pop("target", None)

    return content.decode_contents() if hasattr(content, "decode_contents") else str(content)


# ---------------------------------------------------------------------------
# Page template
# ---------------------------------------------------------------------------

def _page_html(title: str, body: str, sidebar_html: str,
               prev_link: str | None, prev_title: str,
               next_link: str | None, next_title: str,
               course_name: str, page_num: int, total_pages: int,
               logo: bool = False) -> str:

    prev_btn = (
        f'<a href="{prev_link}" class="nav-btn nav-btn-prev">'
        f'&#8592; <span><span class="nav-btn-label">Previous</span>{_escape(prev_title[:50])}</span></a>'
        if prev_link else
        '<span class="nav-btn nav-btn-prev disabled">&#8592; Previous</span>'
    )
    next_btn = (
        f'<a href="{next_link}" class="nav-btn nav-btn-next">'
        f'<span><span class="nav-btn-label">Next</span>{_escape(next_title[:50])}</span> &#8594;</a>'
        if next_link else
        '<span class="nav-btn nav-btn-next disabled">Next &#8594;</span>'
    )

    logo_html = (
        '<div id="sidebar-logo"><img src="../images/sfu-logo.png" alt="SFU"></div>'
        if logo else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>

<nav id="sidebar">
  {logo_html}
  <div id="sidebar-header">
    Course
    <div id="sidebar-title">{_escape(course_name)}</div>
  </div>
  {sidebar_html}
</nav>

<div id="main">
  <div id="content">
    <h1>{_escape(title)}</h1>
    {body}
    <div id="page-nav">
      {prev_btn}
      <div id="page-nav-center">{page_num} / {total_pages}</div>
      {next_btn}
    </div>
  </div>
</div>

<script src="../nav.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Sidebar builder
# ---------------------------------------------------------------------------

def _build_sidebar(modules_with_pages: list[dict], current_slug: str) -> str:
    html_parts = []
    for mod in modules_with_pages:
        pages = mod["pages"]
        if not pages:
            continue
        is_open = any(p["slug"] == current_slug for p in pages)
        open_class = " open" if is_open else ""
        mod_title = _escape(mod["title"])
        html_parts.append(
            f'<div class="module{open_class}">'
            f'<button class="module-toggle">{mod_title} <span class="arrow">&#9654;</span></button>'
            f'<ul class="module-pages">'
        )
        for page in pages:
            href = f"../{page['file']}"
            label = _escape(page["title"])
            html_parts.append(f'<li><a href="{href}">{label}</a></li>')
        html_parts.append("</ul></div>")
    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_site(course_dir: Path, out_dir: Path,
               module_positions: set[int] | None = None,
               title_override: str | None = None,
               include_unpublished: bool = False,
               exclude_titles: set[str] | None = None) -> None:
    t0 = time.perf_counter()

    meta: dict = _read_json(course_dir / "course" / "course_metadata.json") or {}
    course_name = title_override or meta.get("name") or course_dir.name

    modules_data: list = _read_json(course_dir / "modules" / "modules.json") or []
    if not modules_data:
        raise RuntimeError(f"No modules found in {course_dir}")

    file_id_map = _build_file_id_map(course_dir)

    pages_dir = course_dir / "pages"
    slug_map: dict[str, Path] = {}
    if pages_dir.exists():
        for page_dir in pages_dir.iterdir():
            if not page_dir.is_dir():
                continue
            slug = re.sub(r"^\d+_", "", page_dir.name)
            slug_map[slug] = page_dir

    session = requests.Session()
    token = os.getenv("CANVAS_TARGET_TOKEN") or os.getenv("CANVAS_SOURCE_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    # Collect ordered pages across all modules (optionally filtered by position)
    ordered_pages: list[dict] = []
    modules_with_pages: list[dict] = []

    # Build the published-only list first so position filter is 1-based within that set
    published_mods = [
        m for m in modules_data
        if include_unpublished or m.get("published") is not False
    ]

    for published_index, mod in enumerate(published_mods, start=1):
        if module_positions and published_index not in module_positions:
            continue
        mod_title = mod.get("name") or f"Module {published_index}"
        mod_pages = []
        for item in mod.get("items", []):
            if item.get("type") != "Page":
                continue
            slug = item.get("page_url") or ""
            title = (item.get("title") or "").strip()
            if not slug or not title:
                continue
            page_dir = slug_map.get(slug)
            if not page_dir:
                continue
            if exclude_titles and title.strip().lower() in {t.lower() for t in exclude_titles}:
                continue
            filename = f"pages/{_slug_to_filename(slug)}"
            entry = {"slug": slug, "title": title, "page_dir": page_dir, "file": filename}
            ordered_pages.append(entry)
            mod_pages.append(entry)
        modules_with_pages.append({"title": mod_title, "pages": mod_pages})

    if not ordered_pages:
        raise RuntimeError("No pages found in module structure.")

    # Create output directories
    pages_out = out_dir / "pages"
    images_out = out_dir / "images"
    files_out = out_dir / "files"
    pages_out.mkdir(parents=True, exist_ok=True)
    images_out.mkdir(parents=True, exist_ok=True)
    files_out.mkdir(parents=True, exist_ok=True)

    # Write CSS and JS
    (out_dir / "style.css").write_text(CSS, encoding="utf-8")
    (out_dir / "nav.js").write_text(NAV_JS, encoding="utf-8")

    # Copy branding logo if available
    logo_src = REPO_ROOT / "export" / "data" / "target_dump" / "site_resources" / "SFU@2x.png"
    has_logo = logo_src.exists()
    if has_logo:
        (images_out / "sfu-logo.png").write_bytes(logo_src.read_bytes())

    # Build slug→filename map for internal link rewriting
    slug_to_file: dict[str, str] = {p["slug"]: p["file"] for p in ordered_pages}

    # Generate each page
    total = len(ordered_pages)
    for i, page in enumerate(ordered_pages):
        slug = page["slug"]
        title = page["title"]
        page_dir = page["page_dir"]
        html_path = page_dir / "index.html"
        if not html_path.exists():
            continue

        raw_html = html_path.read_text(encoding="utf-8")
        body = _process_html(raw_html, file_id_map, images_out, files_out, session, slug_to_file)
        sidebar_html = _build_sidebar(modules_with_pages, slug)

        prev_page = ordered_pages[i - 1] if i > 0 else None
        next_page = ordered_pages[i + 1] if i < total - 1 else None

        html = _page_html(
            title=title,
            body=body,
            sidebar_html=sidebar_html,
            prev_link=f"../{prev_page['file']}" if prev_page else None,
            prev_title=prev_page["title"] if prev_page else "",
            next_link=f"../{next_page['file']}" if next_page else None,
            next_title=next_page["title"] if next_page else "",
            course_name=course_name,
            page_num=i + 1,
            total_pages=total,
            logo=has_logo,
        )

        out_file = out_dir / page["file"]
        out_file.write_text(html, encoding="utf-8")

    # Write index.html that redirects to first page
    first = ordered_pages[0]["file"]
    (out_dir / "index.html").write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={first}"></head>'
        f'<body><a href="{first}">Enter course</a></body></html>',
        encoding="utf-8",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  Course:   {course_name}")
    if module_positions:
        print(f"  Modules:  {sorted(module_positions)}")
    print(f"  Pages:    {total}")
    print(f"  Output:   {out_dir}")
    print(f"  Time:     {elapsed:.1f}s")
    print(f"\n  Launch:   python -m http.server 8000 --directory \"{out_dir}\"")
    print(f"  Open:     http://localhost:8000/index.html")


def main() -> int:
    p = argparse.ArgumentParser(description="Build a static HTML site from an exported Canvas course")
    p.add_argument("--course-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory (default: <course-dir>/site)")
    p.add_argument("--modules", default=None,
                   help="Comma-separated module position numbers to include (e.g. 1,2,3). "
                        "Omit to include all modules.")
    p.add_argument("--title", default=None,
                   help="Override the course title shown in the sidebar and page titles.")
    p.add_argument("--include-unpublished", action="store_true",
                   help="Include modules marked published=false (skipped by default).")
    p.add_argument("--exclude", default=None,
                   help="Semicolon-separated page titles to omit (e.g. \"Contact Information and Assistance\").")
    args = p.parse_args()

    course_dir = args.course_dir.resolve()
    if not course_dir.is_dir():
        p.error(f"Course directory not found: {course_dir}")

    module_positions: set[int] | None = None
    if args.modules:
        try:
            module_positions = {int(n.strip()) for n in args.modules.split(",")}
        except ValueError:
            p.error("--modules must be comma-separated integers, e.g. 1,2,3")

    exclude_titles: set[str] | None = None
    if args.exclude:
        exclude_titles = {t.strip() for t in args.exclude.split(";") if t.strip()}

    out_dir = args.out or (course_dir / "site")
    print(f"Building site for {course_dir.name}...")
    build_site(course_dir, out_dir, module_positions=module_positions,
               title_override=args.title,
               include_unpublished=args.include_unpublished,
               exclude_titles=exclude_titles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
