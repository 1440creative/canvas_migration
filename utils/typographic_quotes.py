from __future__ import annotations

from typing import Dict, Iterable, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString, Tag

from logging_setup import get_logger
from utils.api import CanvasAPI
from utils.search_replace_html import ContentStats, _list_assignments, _list_discussions, _list_pages

LDQUO = "“"  # left double quotation mark  "
RDQUO = "”"  # right double quotation mark  "
LSQUO = "‘"  # left single quotation mark   '
RSQUO = "’"  # right single quotation mark  '

_SKIP_TAGS = frozenset({"code", "pre", "script", "style", "kbd", "samp", "var"})
_OPEN_CONTEXT = frozenset(" \t\n\r\f\v([{—–-")


def _smart_quotes(text: str) -> Tuple[str, int]:
    """Replace ASCII straight quotes with typographic quotes in a plain-text string."""
    if '"' not in text and "'" not in text:
        return text, 0

    chars = list(text)
    count = 0
    n = len(text)
    for i, ch in enumerate(chars):
        prev = text[i - 1] if i > 0 else " "
        nxt = text[i + 1] if i < n - 1 else " "

        if ch == '"':
            if i == 0 or prev in _OPEN_CONTEXT:
                chars[i] = LDQUO
            else:
                chars[i] = RDQUO
            count += 1

        elif ch == "'":
            if prev.isalpha() and nxt.isalpha():
                # Contraction / possessive apostrophe
                chars[i] = RSQUO
            elif i == 0 or prev in _OPEN_CONTEXT:
                chars[i] = LSQUO
            else:
                chars[i] = RSQUO
            count += 1

    return "".join(chars), count


def _in_skip_tag(node: NavigableString) -> bool:
    for parent in node.parents:
        if isinstance(parent, Tag) and parent.name in _SKIP_TAGS:
            return True
    return False


def apply_smart_quotes(html: str) -> Tuple[str, int]:
    """
    Apply typographic-quote conversion to HTML text nodes only.

    Skips content inside code/pre/script/style/kbd/samp/var and never touches
    HTML attributes. Returns (updated_html, replacement_count).
    """
    if not html or ('"' not in html and "'" not in html):
        return html, 0

    soup = BeautifulSoup(html, "html.parser")
    total = 0
    for node in soup.find_all(string=True):
        if _in_skip_tag(node):
            continue
        new_text, count = _smart_quotes(str(node))
        if count:
            node.replace_with(NavigableString(new_text))
            total += count
    return str(soup), total


def _page_endpoint(course_id: int, slug: str) -> str:
    return f"/courses/{course_id}/pages/{quote(slug, safe='')}"


def _process_pages(
    api: CanvasAPI,
    course_id: int,
    *,
    dry_run: bool,
    log,
    progress_every: int,
) -> ContentStats:
    stats = ContentStats()
    pages = _list_pages(api, course_id)
    pages.sort(key=lambda p: (p.get("position") or 0, p.get("title") or "", p.get("id") or 0))
    total = len(pages)

    for idx, page in enumerate(pages, start=1):
        if progress_every > 0 and (idx % progress_every == 0 or idx == total):
            log.info("pages %d/%d scanned", idx, total)

        slug = page.get("url") or page.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        stats.scanned += 1

        try:
            detail = api.get(_page_endpoint(course_id, slug))
        except Exception as exc:
            stats.failed += 1
            log.warning("page fetch failed slug=%s err=%s", slug, exc)
            continue

        body = detail.get("body") if isinstance(detail, dict) else None
        if not isinstance(body, str):
            body = page.get("body")
        if not isinstance(body, str):
            continue

        updated, count = apply_smart_quotes(body)
        if count == 0:
            continue

        stats.matched += 1
        stats.replacements += count

        if dry_run:
            log.info("dry-run page slug=%s replacements=%d", slug, count)
            continue

        try:
            api.put(_page_endpoint(course_id, slug), json={"wiki_page": {"body": updated}})
            stats.updated += 1
            log.info("updated page slug=%s replacements=%d", slug, count)
        except Exception as exc:
            stats.failed += 1
            log.warning("page update failed slug=%s err=%s", slug, exc)

    return stats


def _process_assignments(
    api: CanvasAPI,
    course_id: int,
    *,
    dry_run: bool,
    log,
    progress_every: int,
) -> ContentStats:
    stats = ContentStats()
    assignments = _list_assignments(api, course_id)
    total = len(assignments)

    for idx, assignment in enumerate(assignments, start=1):
        if progress_every > 0 and (idx % progress_every == 0 or idx == total):
            log.info("assignments %d/%d scanned", idx, total)

        assignment_id = assignment.get("id")
        try:
            assignment_id = int(assignment_id)
        except (TypeError, ValueError):
            continue
        stats.scanned += 1

        try:
            detail = api.get(f"/courses/{course_id}/assignments/{assignment_id}")
        except Exception as exc:
            stats.failed += 1
            log.warning("assignment fetch failed id=%s err=%s", assignment_id, exc)
            continue

        description = detail.get("description") if isinstance(detail, dict) else None
        if not isinstance(description, str):
            description = assignment.get("description")
        if not isinstance(description, str):
            continue

        updated, count = apply_smart_quotes(description)
        if count == 0:
            continue

        stats.matched += 1
        stats.replacements += count

        if dry_run:
            log.info("dry-run assignment id=%s replacements=%d", assignment_id, count)
            continue

        try:
            api.put(
                f"/courses/{course_id}/assignments/{assignment_id}",
                json={"assignment": {"description": updated}},
            )
            stats.updated += 1
            log.info("updated assignment id=%s replacements=%d", assignment_id, count)
        except Exception as exc:
            stats.failed += 1
            log.warning("assignment update failed id=%s err=%s", assignment_id, exc)

    return stats


def _process_discussions(
    api: CanvasAPI,
    course_id: int,
    *,
    dry_run: bool,
    log,
    progress_every: int,
    only_announcements: bool = False,
) -> ContentStats:
    stats = ContentStats()
    topics = _list_discussions(api, course_id, only_announcements=only_announcements)
    label = "announcements" if only_announcements else "discussions"
    total = len(topics)

    for idx, topic in enumerate(topics, start=1):
        if progress_every > 0 and (idx % progress_every == 0 or idx == total):
            log.info("%s %d/%d scanned", label, idx, total)

        if not only_announcements and topic.get("is_announcement") is True:
            continue

        topic_id = topic.get("id")
        try:
            topic_id = int(topic_id)
        except (TypeError, ValueError):
            continue
        stats.scanned += 1

        try:
            detail = api.get(f"/courses/{course_id}/discussion_topics/{topic_id}")
        except Exception as exc:
            stats.failed += 1
            log.warning("%s fetch failed id=%s err=%s", label, topic_id, exc)
            continue

        message = detail.get("message") if isinstance(detail, dict) else None
        if not isinstance(message, str):
            message = topic.get("message")
        if not isinstance(message, str):
            continue

        updated, count = apply_smart_quotes(message)
        if count == 0:
            continue

        stats.matched += 1
        stats.replacements += count

        if dry_run:
            log.info("dry-run %s id=%s replacements=%d", label, topic_id, count)
            continue

        try:
            api.put(
                f"/courses/{course_id}/discussion_topics/{topic_id}",
                json={"message": updated},
            )
            stats.updated += 1
            log.info("updated %s id=%s replacements=%d", label, topic_id, count)
        except Exception as exc:
            stats.failed += 1
            log.warning("%s update failed id=%s err=%s", label, topic_id, exc)

    return stats


def fix_quotes(
    *,
    api: CanvasAPI,
    course_ids: Iterable[int],
    include_pages: bool = True,
    include_assignments: bool = True,
    include_discussions: bool = True,
    dry_run: bool = False,
    progress_every: int = 25,
) -> Dict[int, Dict[str, Dict[str, int]]]:
    """
    Apply typographic-quote conversion across pages, assignments, and discussions
    for each course_id. Returns per-course per-content-type counters.
    """
    summary: Dict[int, Dict[str, Dict[str, int]]] = {}

    for course_id in course_ids:
        log = get_logger(artifact="curly-quotes", course_id=course_id)
        counts: Dict[str, ContentStats] = {}

        if include_pages:
            counts["pages"] = _process_pages(
                api, course_id, dry_run=dry_run, log=log, progress_every=progress_every
            )
        if include_assignments:
            counts["assignments"] = _process_assignments(
                api, course_id, dry_run=dry_run, log=log, progress_every=progress_every
            )
        if include_discussions:
            counts["discussions"] = _process_discussions(
                api, course_id, dry_run=dry_run, log=log, progress_every=progress_every
            )

        counts_dict = {name: stats.to_dict() for name, stats in counts.items()}
        summary[course_id] = counts_dict
        log.info("curly-quotes complete dry_run=%s %s", dry_run, counts_dict)

    return summary


__all__ = ["apply_smart_quotes", "fix_quotes", "LDQUO", "RDQUO", "LSQUO", "RSQUO"]
