# tests/test_export_discussion_entries.py
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests_mock as rm  # noqa: F401 — registers the pytest fixture

from utils.api import CanvasAPI
from export.export_discussion_entries import (
    list_courses_in_subaccount,
    find_matching_discussions,
    fetch_top_level_entries,
    search_and_export,
)

BASE = "https://canvas.test/api/v1"


def _api() -> CanvasAPI:
    return CanvasAPI("https://canvas.test", "tkn")


# ---------------------------------------------------------------------------
# list_courses_in_subaccount
# ---------------------------------------------------------------------------

def test_list_courses_in_subaccount(requests_mock):
    api = _api()
    courses = [{"id": 1, "name": "Course A"}, {"id": 2, "name": "Course B"}]
    requests_mock.get(f"{BASE}/accounts/135/courses", json=courses)

    result = list_courses_in_subaccount(api, 135)
    assert result == courses


# ---------------------------------------------------------------------------
# find_matching_discussions
# ---------------------------------------------------------------------------

def test_find_matching_discussions_filters_by_keyword(requests_mock):
    api = _api()
    topics = [
        {"id": 10, "title": "Week 1 Introduction"},
        {"id": 11, "title": "Week 2 Summary"},
        {"id": 12, "title": "Final Project"},
    ]
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=topics)

    result = find_matching_discussions(api, 1, ["introduction", "final"])
    assert len(result) == 2
    assert {t["id"] for t in result} == {10, 12}
    # course_id should be injected
    assert all(t["course_id"] == 1 for t in result)


def test_find_matching_discussions_case_insensitive(requests_mock):
    api = _api()
    topics = [{"id": 10, "title": "WEEK 1 Introduction"}]
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=topics)

    result = find_matching_discussions(api, 1, ["week 1"])
    assert len(result) == 1


def test_find_matching_discussions_no_matches(requests_mock):
    api = _api()
    topics = [{"id": 10, "title": "Unrelated Topic"}]
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=topics)

    result = find_matching_discussions(api, 1, ["final"])
    assert result == []


# ---------------------------------------------------------------------------
# fetch_top_level_entries
# ---------------------------------------------------------------------------

def test_fetch_top_level_entries(requests_mock):
    api = _api()
    entries = [
        {"id": 100, "user_id": 5, "user_name": "Alice", "message": "Hello",
         "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z"},
    ]
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=entries)

    result = fetch_top_level_entries(api, 1, 10)
    assert len(result) == 1
    assert result[0]["user_name"] == "Alice"


def test_fetch_top_level_entries_empty(requests_mock):
    api = _api()
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[])

    result = fetch_top_level_entries(api, 1, 10)
    assert result == []


# ---------------------------------------------------------------------------
# search_and_export — JSON output
# ---------------------------------------------------------------------------

def test_search_and_export_json_output(requests_mock, tmp_path):
    api = _api()

    # courses
    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "Course A"},
    ])
    # topics
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[
        {"id": 10, "title": "Week 1 Intro"},
    ])
    # entries
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[
        {"id": 100, "user_id": 5, "user_name": "Alice", "message": "Hi",
         "created_at": "2025-01-01T00:00:00Z"},
    ])

    results = search_and_export(api, 135, ["week 1"], tmp_path)
    assert len(results) == 1
    assert results[0]["entry_count"] == 1

    # Check JSON files exist
    topic_dir = tmp_path / "1" / "discussion_entries" / "10_week-1-intro"
    assert (topic_dir / "topic_metadata.json").exists()
    assert (topic_dir / "entries.json").exists()

    meta = json.loads((topic_dir / "topic_metadata.json").read_text())
    assert meta["course_id"] == 1
    assert meta["matched_keyword"] == "week 1"
    assert meta["entry_count"] == 1

    entries = json.loads((topic_dir / "entries.json").read_text())
    assert len(entries) == 1
    assert entries[0]["user_name"] == "Alice"


# ---------------------------------------------------------------------------
# search_and_export — CSV output
# ---------------------------------------------------------------------------

def test_search_and_export_csv_output(requests_mock, tmp_path):
    api = _api()

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "Course A"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[
        {"id": 10, "title": "Week 1 Intro"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[
        {"id": 100, "user_id": 5, "user_name": "Alice", "message": "Hello world",
         "created_at": "2025-01-01T00:00:00Z"},
        {"id": 101, "user_id": 6, "user_name": "Bob", "message": "Hey there",
         "created_at": "2025-01-02T00:00:00Z"},
    ])

    search_and_export(api, 135, ["week 1"], tmp_path)

    csv_path = tmp_path / "discussion_entry_search_results.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["course_name"] == "Course A"
    assert rows[0]["topic_title"] == "Week 1 Intro"
    assert rows[0]["user_name"] == "Alice"
    assert rows[1]["user_name"] == "Bob"


def test_search_and_export_no_entries_csv_row(requests_mock, tmp_path):
    api = _api()

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "Course A"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[
        {"id": 10, "title": "Final Review"},
    ])
    # No entries
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[])

    search_and_export(api, 135, ["final"], tmp_path)

    csv_path = tmp_path / "discussion_entry_search_results.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["topic_title"] == "Final Review"
    assert rows[0]["entry_id"] == ""


# ---------------------------------------------------------------------------
# search_and_export — course_code filter
# ---------------------------------------------------------------------------

def test_search_and_export_filters_by_course_code(requests_mock, tmp_path):
    api = _api()

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "CHRM 101 Intro", "course_code": "CHRM 101"},
        {"id": 2, "name": "PRP 200 Advanced", "course_code": "PRP 200"},
        {"id": 3, "name": "CHRM 301 Seminar", "course_code": "CHRM 301"},
    ])
    # Only CHRM courses should be queried for topics
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[
        {"id": 10, "title": "Week 1 Intro"},
    ])
    requests_mock.get(f"{BASE}/courses/3/discussion_topics", json=[])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[
        {"id": 100, "user_id": 5, "user_name": "Alice", "message": "Hi",
         "created_at": "2025-01-01T00:00:00Z"},
    ])

    results = search_and_export(api, 135, ["week 1"], tmp_path, course_code="CHRM")
    assert len(results) == 1
    assert results[0]["course_id"] == 1


def test_search_and_export_course_code_case_insensitive(requests_mock, tmp_path):
    api = _api()

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "CHRM 101", "course_code": "CHRM 101"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[])

    results = search_and_export(api, 135, ["week 1"], tmp_path, course_code="chrm")
    # Should still match — no topics, so empty results, but no error
    assert results == []


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

SCRIPT = str(Path(__file__).resolve().parents[1] / "scripts" / "search_discussion_entries.py")


def test_cli_main_requires_env_vars():
    """CLI exits with code 2 when credentials are missing."""
    env = {k: v for k, v in os.environ.items()}
    # Remove any Canvas env vars and prevent .env file loading
    for key in list(env):
        if key.startswith("CANVAS_"):
            del env[key]
    env["PYTHON_DOTENV_DISABLE"] = "1"

    result = subprocess.run(
        [sys.executable, SCRIPT, "--subaccount-id", "135", "--keywords", "week 1"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 2


def test_cli_main_end_to_end(requests_mock, tmp_path):
    """Full CLI run with mocked API produces output."""
    api = _api()

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[
        {"id": 1, "name": "Course A"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics", json=[
        {"id": 10, "title": "Week 1 Intro"},
    ])
    requests_mock.get(f"{BASE}/courses/1/discussion_topics/10/entries", json=[
        {"id": 100, "user_id": 5, "user_name": "Alice", "message": "Hi",
         "created_at": "2025-01-01T00:00:00Z"},
    ])

    # Import and call main() directly so requests_mock intercepts
    from scripts.search_discussion_entries import main

    exit_code = main([
        "--subaccount-id", "135",
        "--keywords", "week 1",
        "--output-dir", str(tmp_path),
    ], api_override=api)

    assert exit_code == 0
    assert (tmp_path / "discussion_entry_search_results.csv").exists()


def test_cli_instance_switch(requests_mock, tmp_path, monkeypatch):
    """--instance target reads CANVAS_TARGET_* env vars."""
    monkeypatch.setenv("CANVAS_TARGET_URL", "https://canvas.test")
    monkeypatch.setenv("CANVAS_TARGET_TOKEN", "tkn")

    requests_mock.get(f"{BASE}/accounts/135/courses", json=[])

    from scripts.search_discussion_entries import main

    exit_code = main([
        "--subaccount-id", "135",
        "--keywords", "week 1",
        "--instance", "target",
        "--output-dir", str(tmp_path),
    ])

    assert exit_code == 0
