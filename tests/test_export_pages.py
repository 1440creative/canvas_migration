# tests/test_export_pages.py
import json
import pytest
import re
import requests_mock
from pathlib import Path
from export.export_pages import export_pages

def test_export_pages_creates_files_and_metadata(tmp_path, requests_mock):
    course_id = 101
    base_url = "https://canvas.test/api/v1/"
    
    # Example mock data
    pages_list = [
        {"title": "Lesson 1", "url": "lesson-1", "body": "<h1>Lesson 1</h1><p>This is a test page with <strong>HTML content</strong>.</p>", "published": True},
        {"title": "Lesson 2", "url": "lesson-2", "body": "<h1>Lesson 2</h1><p>This is a test page with <strong>HTML content</strong>.</p>", "published": False},
    ]

    # Mock the "list all pages" endpoint (returns a list)
    requests_mock.get(
        re.compile(
            fr"https://canvas\.test/api/v1/courses/{course_id}/pages(\?.*)?$"
        ),
        json=pages_list
    )

    # Loop to mock each individual page (returns a dict)
    for idx, page in enumerate(pages_list, start=1):
        slug = page["url"]
        requests_mock.get(
            re.compile(f"https://canvas.test/api/v1/courses/{course_id}/pages/{slug}$"),
            json={
                "page_id": 40 + idx,  # just some unique ID
                "title": page["title"],
                "body": page["body"],
                "published": page["published"]
            }
        )
    
    # ###
    # pages_list = [
    #     {
    #         "url": "intro",
    #         "title": "Introduction",
    #         "published": True
    #     },
    #     {
    #         "url": "lesson-1",
    #         "title": "Lesson One",
    #         "published": True
    #     }
    # ]

    # # List all pages (index endpoint)
    # requests_mock.get(
    #     #f"{base_url}/courses/{course_id}/pages",
    #     re.compile(f"https://canvas.test/api/v1/courses/{course_id}/pages.*"),
    #     json=pages_list
    # )

    # # Loop through and mock each page detail endpoint
    # for idx, page in enumerate(pages_list, start=1):
    #     requests_mock.get(
    #         f"{base_url}/courses/{course_id}/pages/{page['url']}",
    #         json={
    #             "page_id": 40 + idx,  # just some unique ID
    #             "title": page["title"],
    #             "body": f"<h1>{page['title']}</h1>",
    #             "html_url": f"{base_url.replace('/api/v1', '')}/courses/{course_id}/pages/{page['url']}",
    #             "published": page["published"]
    #         }
    #     )
        
    # ###
    
    # # Mock the pages list endpoint
    # requests_mock.get(
    #     re.compile(f"https://canvas.test/api/v1/courses/{course_id}/pages.*"),
    #     json=[{"url": "intro", "title": "Introduction"}]
    # )
    
    # # Mock details for each page
    # requests_mock.get(
    #     f"{base_url}/courses/{course_id}/pages/intro",
    #     json={
    #         "page_id": 42,
    #         "body": "<h1>Intro</h1>",
    #         "title": "Introduction",
    #         "html_url": f"{base_url}/courses/{course_id}/pages/intro",
    #         "published": True
    #     }
    # )
    # requests_mock.get(
    #     f"{base_url}/courses/{course_id}/pages/lesson-1",
    #     json={
    #         "page_id": 43,
    #         "body": "<h1>Lesson 1</h1>",
    #         "title": "Lesson One",
    #         "html_url": f"{base_url.replace('/api/v1', '')}/courses/{course_id}/pages/lesson-1",
    #         "published": True
    #     }
    # )
    
    # Patch the API base URL for source_api and fetch_all to use this base
    from utils.api import source_api
    source_api.base_url = base_url
    
    # Run export_pages with real filesystem writes in tmp_path
    metadata = export_pages(course_id, output_dir=tmp_path)
    
    # Paths
    course_dir = tmp_path / str(course_id) / "pages"
    meta_file = tmp_path / str(course_id) / "pages_metadata.json"
    
    print(f"Checking directory: {course_dir}")
    print(f"Lesson-1 HTML exists? {(course_dir / 'lesson-1.html').exists()}")
    print(f"Lesson-1 HTML exists? {(course_dir / 'lesson-2.html').exists()}")
    print(f"Metadata file exists? {meta_file.exists()}")

    
    # Check files created
  
    assert (course_dir / "lesson-1.html").exists()
    assert (course_dir / "lesson-2.html").exists()
    assert meta_file.exists()
    
    # Check HTML content 
    with open(course_dir / "lesson-1.html", encoding="utf-8") as f:
        content = f.read()
        assert "<h1>Lesson 1</h1>" in content
   
    with open(course_dir / "lesson-2.html", encoding="utf-8") as f:
        content = f.read()    
        assert "<h1>Lesson 2</h1>" in content
    
    # Check metadata JSON content
    with open(meta_file, encoding="utf-8") as f:
        data = json.load(f)
        
    print("Metadata JSON content loaded from file:")
    print(data)  # See exactly what’s inside
    
    assert len(data) == 2
    assert data[0]["slug"] == "lesson-1"
    assert data[0]["page_id"] == 41
    assert data[0]["published"] is True
    assert data[1]["slug"] == "lesson-2"
    assert data[1]["page_id"] == 42
    assert data[1]["published"] is False