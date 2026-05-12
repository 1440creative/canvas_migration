#!/usr/bin/env python3
"""
Assemble an epub from an exported Canvas course.

Uses the module structure as the backbone, pages in module order,
HTML pages only. Images are resolved from local files first,
fetched from Canvas if missing. SubHeaders are included only when
the title is unique (not already used as a page title).

Usage:
  python scripts/make_epub.py --course-dir export/data/target_dump/3001
  python scripts/make_epub.py --course-dir export/data/target_dump/3001 --out my.epub
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
    from ebooklib import epub
except ImportError:
    sys.exit("ebooklib is required: pip install ebooklib")

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    sys.exit("beautifulsoup4 is required: pip install beautifulsoup4")

import requests

DEFAULT_BRAND_DIR = REPO_ROOT / "assets" / "brand"

def _watermark_html(text: str, color: str, opacity: float, rotate_deg: int) -> str:
    """Return an HTML div with inline SVG watermark to inject into each chapter body."""
    return (
        f'<div aria-hidden="true" style="position:absolute;top:0;left:0;width:100%;height:100%;'
        f'overflow:hidden;pointer-events:none;z-index:0;">'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
        f'style="position:absolute;top:0;left:0;">'
        f'<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" '
        f'font-family="Georgia,serif" font-size="1.4em" font-weight="bold" '
        f'fill="{color}" opacity="{opacity}" '
        f'transform="rotate({rotate_deg} 0 0) translate(0,0)" '
        f'transform-origin="50% 50%">{text}</text>'
        f'</svg>'
        f'</div>'
    )

MINIMAL_CSS = """
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1.5em 2em;
    color: #1a1a1a;
}
h1 { font-size: 1.5em; margin-top: 1.2em; }
h2 { font-size: 1.25em; margin-top: 1em; }
h3 { font-size: 1.1em; margin-top: 0.9em; }
p  { margin: 0.6em 0; }
a  { color: #2a5db0; text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #ccc; padding: 0.4em 0.6em; text-align: left; }
th { background: #f0f0f0; font-weight: bold; }
blockquote { border-left: 3px solid #ccc; margin: 1em 0; padding-left: 1em; color: #555; }
pre, code { font-family: 'Courier New', monospace; font-size: 0.9em; }
pre { background: #f8f8f8; padding: 0.8em; overflow-x: auto; }
"""


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_brand(brand_dir: Path) -> dict:
    cfg_path = brand_dir / "brand.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _embed_image_file(book: epub.EpubBook, img_path: Path, uid: str) -> str | None:
    """Add an image file to the epub and return its internal path, or None if missing."""
    if not img_path.exists():
        return None
    img_bytes = img_path.read_bytes()
    guessed, _ = mimetypes.guess_type(img_path.name)
    mime = guessed or "image/png"
    ext = img_path.suffix.lstrip(".") or "png"
    item = epub.EpubImage()
    item.uid = uid
    item.file_name = f"images/{uid}.{ext}"
    item.media_type = mime
    item.content = img_bytes
    book.add_item(item)
    return item.file_name


def _make_title_page(book: epub.EpubBook, course_name: str, author: str | None,
                     brand: dict, brand_dir: Path) -> epub.EpubHtml:
    """Build a branded title page and add it to the book."""
    cfg = brand.get("branding", {})
    institution = cfg.get("institution", "")
    tagline = cfg.get("tagline", "")
    logo_file = cfg.get("logo", "")

    logo_tag = ""
    if logo_file:
        logo_path = brand_dir / logo_file
        internal = _embed_image_file(book, logo_path, "brand_logo")
        if internal:
            logo_tag = f'<img src="../{internal}" alt="{institution}" style="max-width:260px; margin: 2em auto; display:block;"/>'

    author_line = f"<p>{author}</p>" if author else ""
    tagline_line = f'<p style="color:#666; font-style:italic;">{tagline}</p>' if tagline else ""

    page = epub.EpubHtml(title="Title Page", file_name="chapters/title_page.xhtml", lang="en")
    page.content = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">'
        '<head><title>Title Page</title>'
        '<link rel="stylesheet" type="text/css" href="../style/main.css"/></head>'
        '<body style="text-align:center; padding-top:4em;">'
        f'{logo_tag}'
        f'<h1 style="margin-top:1.5em;">{course_name}</h1>'
        f'{author_line}'
        f'{tagline_line}'
        f'<p style="color:#888; margin-top:3em;">{institution}</p>'
        '</body></html>'
    ).encode("utf-8")
    book.add_item(page)
    return page


def _make_license_page(book: epub.EpubBook, brand: dict, brand_dir: Path) -> epub.EpubHtml:
    """Build a licence page and add it to the book."""
    cfg = brand.get("license", {})
    name = cfg.get("name", "")
    url = cfg.get("url", "")
    statement = cfg.get("statement", "")
    badge_file = cfg.get("badge", "")

    badge_tag = ""
    if badge_file:
        badge_path = brand_dir / badge_file
        internal = _embed_image_file(book, badge_path, "license_badge")
        if internal:
            badge_tag = f'<a href="{url}"><img src="../{internal}" alt="{name}" style="max-width:120px; margin:1em auto; display:block;"/></a>'

    page = epub.EpubHtml(title="Licence", file_name="chapters/license_page.xhtml", lang="en")
    page.content = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">'
        '<head><title>Licence</title>'
        '<link rel="stylesheet" type="text/css" href="../style/main.css"/></head>'
        '<body style="text-align:center; padding-top:3em;">'
        f'<h2>Licence</h2>'
        f'<p>{statement}</p>'
        f'<p><a href="{url}">{name}</a></p>'
        f'{badge_tag}'
        '</body></html>'
    ).encode("utf-8")
    book.add_item(page)
    return page


def _make_toc_page(book: epub.EpubBook, toc_data: list[tuple[str, list[tuple[str, str]]]]) -> epub.EpubHtml:
    """Build an HTML table of contents page. toc_data = [(mod_title, [(page_title, uid), ...]), ...]"""
    rows = []
    for mod_title, pages in toc_data:
        rows.append(f'<h2 style="margin-top:1.2em; border-bottom:1px solid #ccc; padding-bottom:0.2em;">{mod_title}</h2>')
        rows.append('<ul style="margin:0.4em 0 0.8em 1em; padding:0; list-style:disc;">')
        for page_title, uid in pages:
            rows.append(f'<li><a href="{uid}.xhtml">{page_title}</a></li>')
        rows.append('</ul>')

    page = epub.EpubHtml(title="Contents", file_name="chapters/toc_page.xhtml", lang="en")
    page.content = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">'
        '<head><title>Contents</title>'
        '<link rel="stylesheet" type="text/css" href="../style/main.css"/></head>'
        '<body>'
        '<h1>Contents</h1>'
        + ''.join(rows) +
        '</body></html>'
    ).encode("utf-8")
    book.add_item(page)
    return page


def _build_file_id_map(course_dir: Path) -> dict[int, Path]:
    """Map Canvas file IDs to local file paths."""
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
        # The actual file sits alongside the metadata file
        candidate = meta_path.with_suffix("").with_suffix("")  # strip .metadata.json
        if not candidate.exists():
            # Try stripping the .metadata suffix only
            candidate = Path(str(meta_path).replace(".metadata.json", ""))
        if candidate.exists() and candidate.is_file():
            id_map[int(fid)] = candidate
    return id_map


def _file_id_from_url(url: str) -> int | None:
    m = re.search(r"/files/(\d+)", url)
    if m:
        return int(m.group(1))
    return None


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


def _clean_filename(name: str) -> str:
    return re.sub(r"^\d+_\d+__", "", name)


def _local_file_from_contents_url(url: str, local_files_dir: Path) -> Path | None:
    """Map a Canvas file_contents URL to a file in local_files_dir by path."""
    import urllib.parse
    m = re.search(r"file_contents/course[%20 ]+files/(.*)", url, re.I)
    if not m:
        return None
    rel = urllib.parse.unquote(m.group(1).split("?")[0]).lstrip("/")
    # 1. Exact path match
    candidate = local_files_dir / rel
    if candidate.exists() and candidate.is_file():
        return candidate
    # 2. Exact filename match (anywhere in tree)
    name = Path(rel).name
    for found in local_files_dir.rglob(name):
        return found
    # 3. Strip Canvas hash prefix (e.g. 1693940355_372__filename.pdf → filename.pdf)
    clean_name = re.sub(r"^\d+_\d+__", "", name)
    if clean_name != name:
        for found in local_files_dir.rglob(clean_name):
            return found
    return None


def _process_html(
    raw_html: str,
    page_slug: str,
    book: epub.EpubBook,
    file_id_map: dict[int, Path],
    embedded: dict[str, str],
    session: requests.Session,
    files_base_url: str | None = None,
    staged: bool = False,
    staged_images_dir: Path | None = None,
    local_files_dir: Path | None = None,
    upload_files: dict[str, Path] | None = None,
    unmatched_links: list[str] | None = None,
) -> str:
    """Extract body content, embed images, rewrite file links, return clean HTML string."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # Staged pages are body fragments; dump pages have a wrapper div
    if staged:
        content = soup
    else:
        content = soup.find("div", class_="main-content") or soup.find("div", class_="ll-master") or soup

    # Process images
    for img in content.find_all("img"):
        src = img.get("src", "")
        if not src:
            img.decompose()
            continue

        # Staged pages use ../images/<filename> — embed from local staging source
        if staged and src.startswith("../images/") and staged_images_dir:
            fname = src[len("../images/"):]
            img_path = staged_images_dir / fname
            if img_path.exists():
                img_bytes = img_path.read_bytes()
                guessed, _ = mimetypes.guess_type(fname)
                mime = guessed or "image/png"
                ext = img_path.suffix.lstrip(".") or "png"
                content_hash = hashlib.md5(img_bytes).hexdigest()[:12]
                img_uid = f"img_{content_hash}"
                if img_uid not in embedded:
                    epub_img = epub.EpubImage()
                    epub_img.uid = img_uid
                    epub_img.file_name = f"images/{img_uid}.{ext}"
                    epub_img.media_type = mime
                    epub_img.content = img_bytes
                    book.add_item(epub_img)
                    embedded[img_uid] = epub_img.file_name
                img["src"] = f"../images/{img_uid}.{ext}"
            else:
                img.decompose()
            continue

        img_bytes: bytes | None = None
        mime = "image/png"
        ext = "png"

        fid = _file_id_from_url(src)
        local_path: Path | None = file_id_map.get(fid) if fid else None

        if local_path and local_path.exists():
            img_bytes = local_path.read_bytes()
            guessed, _ = mimetypes.guess_type(local_path.name)
            if guessed:
                mime = guessed
            ext = local_path.suffix.lstrip(".") or ext
        elif local_files_dir and "file_contents" in src:
            local_path = _local_file_from_contents_url(src, local_files_dir)
            if local_path:
                img_bytes = local_path.read_bytes()
                guessed, _ = mimetypes.guess_type(local_path.name)
                if guessed:
                    mime = guessed
                ext = local_path.suffix.lstrip(".") or ext
        else:
            clean_src = src.split("?")[0]
            if clean_src in embedded:
                img["src"] = embedded[clean_src]
                continue
            img_bytes = _fetch_image(src, session)
            if img_bytes:
                guessed, _ = mimetypes.guess_type(src.split("?")[0])
                if guessed:
                    mime = guessed

        if not img_bytes:
            img.decompose()
            continue

        content_hash = hashlib.md5(img_bytes).hexdigest()[:12]
        img_uid = f"img_{content_hash}"

        if img_uid not in embedded:
            epub_img = epub.EpubImage()
            epub_img.uid = img_uid
            epub_img.file_name = f"images/{img_uid}.{ext}"
            epub_img.media_type = mime
            epub_img.content = img_bytes
            book.add_item(epub_img)
            embedded[img_uid] = epub_img.file_name

        img["src"] = f"../images/{img_uid}.{ext}"
        for attr in ["data-api-endpoint", "data-api-returntype", "loading", "verifier"]:
            del img[attr]

        embedded[src.split("?")[0]] = f"../images/{img_uid}.{ext}"

    # Rewrite file links
    for a in content.find_all("a", href=True):
        href = a["href"]

        # Staged pages: ../files/<name> → <base-url><url-encoded-name>
        if staged and href.startswith("../files/"):
            import urllib.parse
            filename = href[len("../files/"):]
            if upload_files is not None:
                upload_files[filename] = None  # sentinel — collected separately from staged files dir
            if files_base_url:
                a["href"] = files_base_url.rstrip("/") + "/" + urllib.parse.quote(filename, safe="")
            continue

        # file_contents links → resolve via local_files_dir or rewrite to base URL
        if "file_contents" in href:
            if local_files_dir:
                local_path = _local_file_from_contents_url(href, local_files_dir)
                if local_path:
                    clean = _clean_filename(local_path.name)
                    if upload_files is not None:
                        upload_files[clean] = local_path
                    if files_base_url:
                        a["href"] = files_base_url.rstrip("/") + "/" + __import__("urllib.parse", fromlist=["quote"]).quote(clean, safe="")
                    continue
            if unmatched_links is not None:
                unmatched_links.append(href)
            a["href"] = re.sub(r"\?.*$", "", href)
            continue

        # Canvas /files/<id> URLs → resolve via file_id_map, rewrite to base URL
        fid = _file_id_from_url(href)
        if fid:
            local_path = file_id_map.get(fid)
            if local_path:
                clean = _clean_filename(local_path.name)
                if upload_files is not None:
                    upload_files[clean] = local_path
                if files_base_url:
                    a["href"] = files_base_url.rstrip("/") + "/" + __import__("urllib.parse", fromlist=["quote"]).quote(clean, safe="")
            else:
                if unmatched_links is not None:
                    unmatched_links.append(href)
                # Strip verifier/wrap params at minimum
                a["href"] = re.sub(r"\?.*$", "", href)

    inner = content.decode_contents() if hasattr(content, "decode_contents") else str(content)
    return inner


def build_epub(course_dir: Path | None, out_path: Path,
               source_dir: Path | None = None,
               title_override: str | None = None,
               author: str | None = None,
               files_base_url: str | None = None,
               local_files_dir: Path | None = None,
               upload_dir: Path | None = None,
               branded: bool = False,
               watermark: bool = False,
               licensed: bool = False,
               brand_dir: Path | None = None) -> None:
    t0 = time.perf_counter()

    staged = source_dir is not None

    if staged:
        meta: dict = _read_json(source_dir / "course_metadata.json") or {}
        modules_data: list = _read_json(source_dir / "modules.json") or []
        staged_pages_dir = source_dir / "pages"
        slug_set: set[str] = {f.stem for f in staged_pages_dir.glob("*.html")}
        file_id_map: dict[int, Path] = {}
    else:
        meta = _read_json(course_dir / "course" / "course_metadata.json") or {}
        modules_data = _read_json(course_dir / "modules" / "modules.json") or []
        file_id_map = _build_file_id_map(course_dir)
        print(f"  Local file map: {len(file_id_map)} files indexed")
        pages_dir = course_dir / "pages"
        slug_map: dict[str, Path] = {}
        if pages_dir.exists():
            for page_dir in pages_dir.iterdir():
                if not page_dir.is_dir():
                    continue
                slug = re.sub(r"^\d+_", "", page_dir.name)
                slug_map[slug] = page_dir

    course_name = title_override or meta.get("name") or (source_dir or course_dir).name
    course_id = meta.get("id") or (source_dir or course_dir).name

    if not modules_data:
        sys.exit("No modules found")

    all_page_titles: set[str] = set()
    for mod in modules_data:
        for item in mod.get("items", []):
            if item.get("type") == "Page":
                all_page_titles.add((item.get("title") or "").strip().lower())

    session = requests.Session()
    token = __import__("os").getenv("CANVAS_TARGET_TOKEN") or __import__("os").getenv("CANVAS_SOURCE_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    book = epub.EpubBook()
    book.set_identifier(f"canvas-course-{course_id}")
    book.set_title(course_name)
    book.set_language("en")
    if author:
        book.add_author(author)

    resolved_brand_dir = brand_dir or DEFAULT_BRAND_DIR
    brand = _load_brand(resolved_brand_dir) if (branded or watermark or licensed) else {}

    # Build CSS — append watermark rules if requested
    main_css = MINIMAL_CSS
    watermark_html = ""
    if watermark:
        wm = brand.get("watermark", {})
        watermark_html = _watermark_html(
            text=wm.get("text", "For personal use only"),
            opacity=wm.get("opacity", 0.08),
            color=wm.get("color", "#888888"),
            rotate_deg=wm.get("rotate_deg", -35),
        )
        main_css += "\nbody { position: relative; }\n"

    css = epub.EpubItem(uid="style", file_name="style/main.css",
                        media_type="text/css", content=main_css.encode())
    book.add_item(css)

    spine: list = ["nav"]
    toc: list = []
    embedded: dict[str, str] = {}
    upload_files: dict[str, Path] = {}
    unmatched_links: list[str] = []
    toc_data: list[tuple[str, list[tuple[str, str]]]] = []
    page_count = 0

    # Branded title page — inserted at front of spine
    if branded:
        title_page = _make_title_page(book, course_name, author, brand, resolved_brand_dir)
        spine.append(title_page)

    for mod in modules_data:
        if mod.get("published") is False:
            continue
        mod_title = mod.get("name") or f"Module {mod.get('position', '')}"
        mod_chapters: list[epub.EpubHtml] = []

        for item in mod.get("items", []):
            itype = item.get("type")
            title = (item.get("title") or "").strip()

            if itype == "SubHeader":
                continue
            if itype != "Page":
                continue

            slug = item.get("page_url") or ""
            if not slug:
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

            body_content = _process_html(
                raw_html, slug, book, file_id_map, embedded, session,
                files_base_url=files_base_url, staged=staged,
                staged_images_dir=source_dir / "images" if staged else None,
                local_files_dir=local_files_dir,
                upload_files=upload_files,
                unmatched_links=unmatched_links)

            uid = f"page_{hashlib.md5(slug.encode()).hexdigest()[:10]}"
            chapter = epub.EpubHtml(title=title, file_name=f"chapters/{uid}.xhtml", lang="en")
            chapter.content = (
                f'<?xml version="1.0" encoding="utf-8"?>'
                f'<!DOCTYPE html>'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">'
                f'<head><title>{title}</title>'
                f'<link rel="stylesheet" type="text/css" href="../style/main.css"/>'
                f'</head><body>'
                f'{watermark_html}'
                f'<h1>{title}</h1>'
                f'{body_content}'
                f'</body></html>'
            ).encode("utf-8")

            book.add_item(chapter)
            spine.append(chapter)
            mod_chapters.append(chapter)
            page_count += 1

        if mod_chapters:
            chapter_links = [
                epub.Link(c.file_name, c.title, c.file_name.replace("chapters/", "").replace(".xhtml", ""))
                for c in mod_chapters
            ]
            toc.append((epub.Section(mod_title), chapter_links))
            toc_data.append((mod_title, [(c.title, c.file_name.replace("chapters/", "").replace(".xhtml", "")) for c in mod_chapters]))

    # TOC page — inserted after title page, before chapters
    toc_page = _make_toc_page(book, toc_data)
    # Find insertion point: after title page if branded, else after "nav"
    insert_at = 2 if branded else 1
    spine.insert(insert_at, toc_page)

    # Licence page — appended at back of spine
    if licensed:
        license_page = _make_license_page(book, brand, resolved_brand_dir)
        spine.append(license_page)
        toc.append(epub.Link("chapters/license_page.xhtml", "Licence", "license_page"))

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)

    import shutil
    total_uploaded = 0
    if upload_dir:
        upload_dir.mkdir(parents=True, exist_ok=True)
        # Files matched from local_files_dir (course-dir mode)
        for clean_name, src_path in upload_files.items():
            if src_path is not None:
                dest = upload_dir / clean_name
                if not dest.exists():
                    shutil.copy2(src_path, dest)
        # Staged files dir — copy everything (staged mode)
        if staged and source_dir:
            staged_files = source_dir / "files"
            if staged_files.is_dir():
                for f in staged_files.iterdir():
                    if f.is_file():
                        dest = upload_dir / f.name
                        if not dest.exists():
                            shutil.copy2(f, dest)
        total_uploaded = sum(1 for f in upload_dir.iterdir() if f.is_file())

    elapsed = time.perf_counter() - t0
    print(f"\n  Course:   {course_name}")
    print(f"  Pages:    {page_count}")
    print(f"  Images:   {len(embedded)}")
    if files_base_url:
        print(f"  Files URL: {files_base_url}")
    print(f"  Output:   {out_path}")
    if upload_dir:
        print(f"  Upload:   {upload_dir} ({total_uploaded} files)")
    if unmatched_links:
        seen = set()
        print(f"\n  Unmatched Canvas links ({len(set(unmatched_links))}):")
        for lnk in unmatched_links:
            clean = re.sub(r"\?.*$", "", lnk)
            if clean not in seen:
                seen.add(clean)
                print(f"    ✗ {clean}")
    print(f"  Time:     {elapsed:.1f}s")


def main() -> int:
    p = argparse.ArgumentParser(description="Build an epub from an exported Canvas course")
    p.add_argument("--course-dir", type=Path, default=None,
                   help="Raw Canvas dump directory (required if --source-dir not given)")
    p.add_argument("--source-dir", type=Path, default=None,
                   help="Staged editable source (from stage_site.py). Use instead of --course-dir.")
    p.add_argument("--out", type=Path, default=None,
                   help="Output epub path (default: <course-dir>/<id>.epub or <source-dir>/<id>.epub)")
    p.add_argument("--title", default=None, help="Override the epub title")
    p.add_argument("--author", default=None, help="Set the epub author/publisher metadata")
    p.add_argument("--files-base-url", default=None,
                   help="Base URL where PDFs/files will be hosted (e.g. http://server/dlog705/). "
                        "Canvas file links are rewritten to point here.")
    p.add_argument("--local-files-dir", type=Path, default=None,
                   help="Directory of manually downloaded Canvas files (images/PDFs). "
                        "Matched to file_contents URLs by path before trying the API.")
    p.add_argument("--upload-dir", type=Path, default=None,
                   help="Collect all matched PDFs/files into this flat folder for web server upload.")
    p.add_argument("--branded", action="store_true",
                   help="Insert a branded title page at the front (uses assets/brand/brand.json).")
    p.add_argument("--watermark", action="store_true",
                   help="Overlay a diagonal watermark on every page via CSS.")
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
        out_path = args.out or (source_dir / f"{source_dir.name}.epub")
        label = source_dir.name
    else:
        course_dir = args.course_dir.resolve()
        if not course_dir.is_dir():
            p.error(f"Course directory not found: {course_dir}")
        source_dir = None
        out_path = args.out or (course_dir / f"{course_dir.name}.epub")
        label = course_dir.name

    local_files_dir = args.local_files_dir.resolve() if args.local_files_dir else None
    if local_files_dir and not local_files_dir.is_dir():
        p.error(f"Local files directory not found: {local_files_dir}")

    upload_dir = args.upload_dir.resolve() if args.upload_dir else None

    print(f"Building epub for {label}...")
    brand_dir = args.brand_dir.resolve() if args.brand_dir else None

    build_epub(course_dir, out_path,
               source_dir=source_dir,
               title_override=args.title,
               author=args.author,
               files_base_url=args.files_base_url,
               local_files_dir=local_files_dir,
               upload_dir=upload_dir,
               branded=args.branded,
               watermark=args.watermark,
               licensed=args.licensed,
               brand_dir=brand_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
