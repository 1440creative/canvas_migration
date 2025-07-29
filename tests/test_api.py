# tests/test_api.py
import os
import pytest
import requests_mock
from utils.api import CanvasAPI

def test_api_initialization():
    api = CanvasAPI("https://example.com/api/v1", "fake_token")
    assert api.base_url.endswith("/")

def test_get_single_object(requests_mock):
    api = CanvasAPI("https://example.com/api/v1", "fake_token")
    requests_mock.get("https://example.com/api/v1/courses/123", json={"id": 123})
    data = api.get("/courses/123")
    assert data["id"] == 123

def test_get_paginated_results(requests_mock):
    api = CanvasAPI("https://example.com/api/v1", "fake_token")
    # First page with next link
    requests_mock.get(
        "https://example.com/api/v1/courses",
        json=[{"id": 1}],
        headers={"link": '<https://example.com/api/v1/courses?page=2>; rel="next"'}
    )
    # Second page
    requests_mock.get("https://example.com/api/v1/courses?page=2", json=[{"id": 2}])
    results = api.get("/courses")
    assert len(results) == 2
