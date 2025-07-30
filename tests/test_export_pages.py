# tests/test_export_pages.py
import os, json
import pytest
import requests_mock
from export.export_pages import export_pages

@pytest.fixture
def tmp_output(tmp_path):
    return tmp_path

def test_export_pages_creates_files_and_metadata(tmp_output, requests_mock):
    course_id = 101
    # Mock the pages list
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/pages",
        json=[{"url": "intro", "title": "Introduction"}] #list not dict
    )
    # Mock the page detail
    requests_mock.get(
        f"https://canvas.test/api/v1/courses/{course_id}/pages/intro",
        json={
            "page_id": 42,
            "body": "<h1>Intro</h1>",
            "title": "Introduction",
            "html_url": "https://canvas.test/courses/101/pages/intro",
            "published": True
        }
    )

    # Patch the API instance to use our fake base URL
    from utils import api
    api.source_api.base_url = "https://canvas.test/api/v1/"

    metadata = export_pages(course_id, output_dir=str(tmp_output))

    # Assertions
    course_dir = tmp_output / str(course_id) / "pages"
    html_file = course_dir / "intro.html"
    meta_file = tmp_output / str(course_id) / "pages_metadata.json"

    # Check files created
    assert html_file.exists()
    assert meta_file.exists()

    # Check HTML content
    with open(html_file, "r", encoding="utf-8") as f:
        assert "<h1>Intro</h1>" in f.read()

    # Check metadata JSON
    with open(meta_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["slug"] == "intro"
    assert data[0]["page_id"] == 42
