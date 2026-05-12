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

        # Staged pages: ../files/<name> → <base-url><name>
        if staged and href.startswith("../files/") and files_base_url:
            filename = href[len("../files/"):]
            a["href"] = files_base_url.rstrip("/") + "/" + filename
            continue

        # Canvas file URLs → resolve via file_id_map, rewrite to base URL
        fid = _file_id_from_url(href)
        if fid and files_base_url:
            local_path = file_id_map.get(fid)
            if local_path:
                clean = _clean_filename(local_path.name)
                a["href"] = files_base_url.rstrip("/") + "/" + clean
            else:
                # No local file — strip verifier/wrap params at minimum
                a["href"] = re.sub(r"\?.*$", "", href)

    inner = content.decode_contents() if hasattr(content, "decode_contents") else str(content)
    return inner


def build_epub(course_dir: Path | None, out_path: Path,
               source_dir: Path | None = None,
               title_override: str | None = None,
               author: str | None = None,
               files_base_url: str | None = None) -> None:
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

    css = epub.EpubItem(uid="style", file_name="style/main.css",
                        media_type="text/css", content=MINIMAL_CSS.encode())
    book.add_item(css)

    spine: list = ["nav"]
    toc: list = []
    embedded: dict[str, str] = {}
    page_count = 0

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
                staged_images_dir=source_dir / "images" if staged else None)

            uid = f"page_{hashlib.md5(slug.encode()).hexdigest()[:10]}"
            chapter = epub.EpubHtml(title=title, file_name=f"chapters/{uid}.xhtml", lang="en")
            chapter.content = (
                f'<?xml version="1.0" encoding="utf-8"?>'
                f'<!DOCTYPE html>'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">'
                f'<head><title>{title}</title>'
                f'<link rel="stylesheet" type="text/css" href="../style/main.css"/>'
                f'</head><body>'
                f'<h1>{title}</h1>'
                f'{body_content}'
                f'</body></html>'
            ).encode("utf-8")

            book.add_item(chapter)
            spine.append(chapter)
            mod_chapters.append(chapter)
            page_count += 1

        if mod_chapters:
            toc.append(epub.Section(mod_title, mod_chapters))

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)

    elapsed = time.perf_counter() - t0
    print(f"\n  Course:   {course_name}")
    print(f"  Pages:    {page_count}")
    print(f"  Images:   {len(embedded)}")
    if files_base_url:
        print(f"  Files URL: {files_base_url}")
    print(f"  Output:   {out_path}")
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

    print(f"Building epub for {label}...")
    build_epub(course_dir, out_path,
               source_dir=source_dir,
               title_override=args.title,
               author=args.author,
               files_base_url=args.files_base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
