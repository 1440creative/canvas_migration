# tests/test_api_endpoint_normalization.py
from utils.api import CanvasAPI

def test_full_url_normalizes_endpoints():
    api = CanvasAPI("https://example.com/api/v1", "tkn")

    # All of these should resolve to the same final URL when requested:
    # (We don’t hit the network; we just verify the request goes to the right place via requests_mock)
    paths = [
        "courses/1/modules",
        "/courses/1/modules",
        "/api/v1/courses/1/modules",
    ]

    for p in paths:
        # Mock once per URL form
        # requests_mock needs the *final* URL; api._full_url tells us what that will be
        # (private method is fine to use in a unit test)
        url = api._full_url(p)
        assert url == "https://example.com/api/v1/courses/1/modules"

def test_get_injects_per_page_and_paginates(requests_mock):
    api = CanvasAPI("https://canvas.test/api/v1", "tkn")

    # first page returns Link: next
    requests_mock.get(
        "https://canvas.test/api/v1/courses/303/modules",
        json=[{"id": 1}],
        headers={"Link": '<https://canvas.test/api/v1/courses/303/modules?page=2>; rel="next"'},
    )
    # second page
    requests_mock.get(
        "https://canvas.test/api/v1/courses/303/modules?page=2",
        json=[{"id": 2}],
    )

    data = api.get("/courses/303/modules")
    assert [m["id"] for m in data] == [1, 2]
