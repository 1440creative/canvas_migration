from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from logging_setup import get_logger
from utils.api import CanvasAPI, list_blueprint_course_ids
from utils.html_postprocessor import replace_anchor_href


@dataclass
class ContentStats:
    scanned: int = 0
    matched: int = 0
    updated: int = 0
    failed: int = 0
    replacements: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "updated": self.updated,
            "failed": self.failed,
            "replacements": self.replacements,
        }


def _list_pages(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    items = api.get(f"/courses/{course_id}/pages")
    return items if isinstance(items, list) else []


def _list_assignments(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    items = api.get(f"/courses/{course_id}/assignments")
    return items if isinstance(items, list) else []


def _list_discussions(
    api: CanvasAPI,
    course_id: int,
    *,
    only_announcements: bool = False,
) -> List[Dict[str, Any]]:
    params = {"only_announcements": True} if only_announcements else None
    items = api.get(f"/courses/{course_id}/discussion_topics", params=params)
    return items if isinstance(items, list) else []


def _safe_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _page_endpoint(course_id: int, slug: str) -> str:
    return f"/courses/{course_id}/pages/{quote(slug, safe='')}"


def _log_progress(log, *, label: str, current: int, total: int, progress_every: int) -> None:
    if progress_every <= 0:
        return
    if current % progress_every == 0 or current == total:
        log.info("%s %d/%d scanned", label, current, total)


def _process_pages(
    api: CanvasAPI,
    course_id: int,
    *,
    target_href: str,
    replacement_href: str,
    dry_run: bool,
    log,
    progress_every: int,
) -> ContentStats:
    stats = ContentStats()
    pages = _list_pages(api, course_id)
    total = len(pages)
    for idx, page in enumerate(pages, start=1):
        _log_progress(log, label="pages", current=idx, total=total, progress_every=progress_every)
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

        body = None
        if isinstance(detail, dict):
            body = _safe_str(detail.get("body"))
        if body is None:
            body = _safe_str(page.get("body"))
        if body is None:
            continue

        updated_html, replacements = replace_anchor_href(
            body,
            target_href=target_href,
            replacement_href=replacement_href,
        )
        if replacements == 0:
            continue

        stats.matched += 1
        stats.replacements += replacements

        if dry_run:
            continue

        try:
            api.put(
                _page_endpoint(course_id, slug),
                json={"wiki_page": {"body": updated_html}},
            )
            stats.updated += 1
        except Exception as exc:
            stats.failed += 1
            log.warning("page update failed slug=%s err=%s", slug, exc)

    return stats


def _process_assignments(
    api: CanvasAPI,
    course_id: int,
    *,
    target_href: str,
    replacement_href: str,
    dry_run: bool,
    log,
    progress_every: int,
) -> ContentStats:
    stats = ContentStats()
    assignments = _list_assignments(api, course_id)
    total = len(assignments)
    for idx, assignment in enumerate(assignments, start=1):
        _log_progress(log, label="assignments", current=idx, total=total, progress_every=progress_every)
        assignment_id = assignment.get("id")
        if not isinstance(assignment_id, int):
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

        description = None
        if isinstance(detail, dict):
            description = _safe_str(detail.get("description"))
        if description is None:
            description = _safe_str(assignment.get("description"))
        if description is None:
            continue

        updated_html, replacements = replace_anchor_href(
            description,
            target_href=target_href,
            replacement_href=replacement_href,
        )
        if replacements == 0:
            continue

        stats.matched += 1
        stats.replacements += replacements

        if dry_run:
            continue

        try:
            api.put(
                f"/courses/{course_id}/assignments/{assignment_id}",
                json={"assignment": {"description": updated_html}},
            )
            stats.updated += 1
        except Exception as exc:
            stats.failed += 1
            log.warning("assignment update failed id=%s err=%s", assignment_id, exc)

    return stats


def _process_discussions(
    api: CanvasAPI,
    course_id: int,
    *,
    target_href: str,
    replacement_href: str,
    dry_run: bool,
    log,
    only_announcements: bool = False,
    progress_every: int = 0,
) -> ContentStats:
    stats = ContentStats()
    topics = _list_discussions(api, course_id, only_announcements=only_announcements)
    total = len(topics)
    label = "announcements" if only_announcements else "discussions"
    for idx, topic in enumerate(topics, start=1):
        _log_progress(log, label=label, current=idx, total=total, progress_every=progress_every)
        if not only_announcements and topic.get("is_announcement") is True:
            continue

        topic_id = topic.get("id")
        if not isinstance(topic_id, int):
            try:
                topic_id = int(topic_id)
            except (TypeError, ValueError):
                continue

        stats.scanned += 1
        try:
            detail = api.get(f"/courses/{course_id}/discussion_topics/{topic_id}")
        except Exception as exc:
            stats.failed += 1
            log.warning("discussion fetch failed id=%s err=%s", topic_id, exc)
            continue

        message = None
        if isinstance(detail, dict):
            message = _safe_str(detail.get("message"))
        if message is None:
            message = _safe_str(topic.get("message"))
        if message is None:
            continue

        updated_html, replacements = replace_anchor_href(
            message,
            target_href=target_href,
            replacement_href=replacement_href,
        )
        if replacements == 0:
            continue

        stats.matched += 1
        stats.replacements += replacements

        if dry_run:
            continue

        try:
            api.put(
                f"/courses/{course_id}/discussion_topics/{topic_id}",
                json={"message": updated_html},
            )
            stats.updated += 1
        except Exception as exc:
            stats.failed += 1
            log.warning("discussion update failed id=%s err=%s", topic_id, exc)

    return stats


def search_and_replace(
    *,
    api: CanvasAPI,
    course_ids: Iterable[int] | None = None,
    account_id: int | None = None,
    target_href: str,
    replacement_href: str,
    include_pages: bool = True,
    include_assignments: bool = True,
    include_discussions: bool = True,
    include_announcements: bool = True,
    dry_run: bool = False,
    progress_every: int = 0,
) -> Dict[int, Dict[str, Dict[str, int]]]:
    """
    Search/replace HTML links in pages, assignments, and discussions.

    If course_ids is None, lookup blueprint courses for the given account_id.
    Returns a dict keyed by course_id with per-content-type counters.
    """
    if course_ids is None:
        if account_id is None:
            raise ValueError("course_ids or account_id is required")
        course_ids = list_blueprint_course_ids(api, account_id=account_id)

    summary: Dict[int, Dict[str, Dict[str, int]]] = {}
    totals: Dict[str, ContentStats] = {}
    for course_id in course_ids:
        log = get_logger(artifact="search-replace", course_id=course_id)
        counts: Dict[str, ContentStats] = {}

        if include_pages:
            counts["pages"] = _process_pages(
                api,
                course_id,
                target_href=target_href,
                replacement_href=replacement_href,
                dry_run=dry_run,
                log=log,
                progress_every=progress_every,
            )
        if include_assignments:
            counts["assignments"] = _process_assignments(
                api,
                course_id,
                target_href=target_href,
                replacement_href=replacement_href,
                dry_run=dry_run,
                log=log,
                progress_every=progress_every,
            )
        if include_discussions:
            counts["discussions"] = _process_discussions(
                api,
                course_id,
                target_href=target_href,
                replacement_href=replacement_href,
                dry_run=dry_run,
                log=log,
                progress_every=progress_every,
            )
        if include_announcements:
            counts["announcements"] = _process_discussions(
                api,
                course_id,
                target_href=target_href,
                replacement_href=replacement_href,
                dry_run=dry_run,
                log=log,
                only_announcements=True,
                progress_every=progress_every,
            )

        counts_dict = {name: stats.to_dict() for name, stats in counts.items()}
        summary[course_id] = counts_dict
        log.info(
            "search/replace complete",
            extra={"dry_run": dry_run, "counts": counts_dict},
        )
        log.info(
            "search/replace counts dry_run=%s %s",
            dry_run,
            counts_dict,
        )

        for name, stats in counts.items():
            agg = totals.setdefault(name, ContentStats())
            agg.scanned += stats.scanned
            agg.matched += stats.matched
            agg.updated += stats.updated
            agg.failed += stats.failed
            agg.replacements += stats.replacements

    overall_log = get_logger(artifact="search-replace", course_id="-")
    overall_counts = {name: stats.to_dict() for name, stats in totals.items()}
    overall_log.info(
        "search/replace overall dry_run=%s %s",
        dry_run,
        overall_counts,
    )

    return summary


__all__ = ["search_and_replace", "ContentStats"]
