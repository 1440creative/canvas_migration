# canvas_calibrator/ingest/content_loader.py
"""
Load course content from export/data/cloud/{course_id}/:
  - Pages (pages/*/index.html)
  - PDFs  (files/02-learning-materials/**/*.pdf)
  - External URLs found in page HTML
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document dataclass
# ---------------------------------------------------------------------------

@dataclass
class Document:
    doc_id: str           # sha256 of source_path / url
    source_type: str      # "page" | "pdf" | "external_url"
    title: str
    source_path: str      # file path or URL
    text: str
    extractable: bool = True
    metadata: dict = field(default_factory=dict)


def _make_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._links: list[str] = []
        self._skip_tags = {"script", "style"}
        self._in_skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._in_skip += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and href.startswith("http"):
                self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._in_skip:
            self._in_skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._in_skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(p.strip() for p in self._parts if p.strip())

    def get_links(self) -> list[str]:
        return self._links


def _parse_html(html: str) -> tuple[str, list[str]]:
    p = _HTMLTextExtractor()
    p.feed(html)
    return p.get_text(), p.get_links()


_CANVAS_HOST_RE = None

def _is_canvas_internal(url: str) -> bool:
    """Return True if the URL is a Canvas internal link (same host or relative)."""
    return (
        "instructure.com" in url
        or "canvas.sfu.ca" in url
        or "canvas-old.sfu.ca" in url
    )


# ---------------------------------------------------------------------------
# Page loader
# ---------------------------------------------------------------------------

def _load_pages(course_root: Path) -> list[Document]:
    docs: list[Document] = []
    pages_dir = course_root / "pages"
    if not pages_dir.exists():
        return docs

    for html_file in sorted(pages_dir.glob("*/index.html")):
        slug = html_file.parent.name
        try:
            html = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.warning("Could not read page %s: %s", html_file, e)
            continue
        text, _ = _parse_html(html)
        if not text.strip():
            continue
        docs.append(Document(
            doc_id=_make_id(str(html_file)),
            source_type="page",
            title=slug,
            source_path=str(html_file),
            text=text,
        ))

    log.info("Loaded %d pages", len(docs))
    return docs


# ---------------------------------------------------------------------------
# PDF loader
# ---------------------------------------------------------------------------

def _load_pdfs(course_root: Path) -> list[Document]:
    docs: list[Document] = []
    files_dir = course_root / "files" / "02-learning-materials"
    if not files_dir.exists():
        return docs

    try:
        import pypdf
    except ImportError:
        log.warning("pypdf not installed — skipping PDF ingestion")
        return docs

    for pdf_file in sorted(files_dir.rglob("*.pdf")):
        try:
            reader = pypdf.PdfReader(str(pdf_file))
            page_count = len(reader.pages)
            if page_count == 0:
                continue

            pages_text: list[str] = []
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")

            full_text = "\n".join(pages_text)
            chars_per_page = len(full_text) / page_count
            extractable = chars_per_page >= 50

            docs.append(Document(
                doc_id=_make_id(str(pdf_file)),
                source_type="pdf",
                title=pdf_file.stem,
                source_path=str(pdf_file),
                text=full_text if extractable else "",
                extractable=extractable,
                metadata={"page_count": page_count},
            ))
            if not extractable:
                log.warning("Scanned PDF (skipping text): %s", pdf_file.name)
            else:
                log.info("Loaded PDF: %s (%d pages)", pdf_file.name, page_count)

        except Exception as e:
            log.warning("Could not read PDF %s: %s", pdf_file, e)

    log.info("Loaded %d PDFs", len(docs))
    return docs


# ---------------------------------------------------------------------------
# External URL loader
# ---------------------------------------------------------------------------

def _load_external_urls(
    course_root: Path,
    skip_fetch: bool = False,
) -> list[Document]:
    docs: list[Document] = []

    # Collect all unique external links from all pages
    pages_dir = course_root / "pages"
    if not pages_dir.exists():
        return docs

    seen_urls: set[str] = set()
    for html_file in sorted(pages_dir.glob("*/index.html")):
        try:
            html = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _, links = _parse_html(html)
        for url in links:
            if not _is_canvas_internal(url) and url not in seen_urls:
                seen_urls.add(url)

    if not seen_urls:
        return docs

    if skip_fetch:
        log.info("--skip-fetch: skipping %d external URLs", len(seen_urls))
        return docs

    try:
        import trafilatura
    except ImportError:
        log.warning("trafilatura not installed — skipping external URL fetching")
        return docs

    for url in sorted(seen_urls):
        try:
            log.info("Fetching external URL: %s", url)
            downloaded = trafilatura.fetch_url(url, timeout=10)
            if downloaded is None:
                log.warning("No content fetched from %s", url)
                time.sleep(2)
                continue

            text = trafilatura.extract(downloaded) or ""
            if not text.strip():
                log.warning("No text extracted from %s", url)
                time.sleep(2)
                continue

            docs.append(Document(
                doc_id=_make_id(url),
                source_type="external_url",
                title=url,
                source_path=url,
                text=text,
                metadata={
                    "url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
            ))
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)

        time.sleep(2)

    log.info("Fetched %d external URLs", len(docs))
    return docs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def load_course_content(
    course_root: str | Path,
    skip_fetch: bool = False,
    no_pdfs: bool = False,
) -> list[Document]:
    """
    Load all course content from the exported course directory.

    Args:
        course_root: path to export/data/cloud/{course_id}/
        skip_fetch:  skip external URL fetching
        no_pdfs:     skip PDF ingestion

    Returns:
        list of Document objects
    """
    course_root = Path(course_root)
    if not course_root.exists():
        raise FileNotFoundError(f"Course export directory not found: {course_root}")

    docs: list[Document] = []
    docs.extend(_load_pages(course_root))
    if not no_pdfs:
        docs.extend(_load_pdfs(course_root))
    docs.extend(_load_external_urls(course_root, skip_fetch=skip_fetch))

    log.info("Total documents loaded: %d", len(docs))
    return docs
