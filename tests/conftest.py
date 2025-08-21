# tests/conftest.py
import pytest

class DummyResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json
    
    def raise_for_status(self):
        """Mimic requests.Response.raise_for_status()"""
        if 400 <= self.status_code < 600:
            raise Exception(f"HTTP {self.status_code} Error")
        return None


class DummyCanvas:
    """
    Minimal Canvas-like wrapper that mimics CanvasAPI's surface.

    Provides post/put/get/delete methods that record calls and
    return DummyResponse objects. This is enough for most importer tests.
    """
    def __init__(self, api_base: str = "https://api.example.edu"):
        self.api_base = api_base.rstrip("/")
        self.calls: list[tuple[str, str, dict | None]] = []

    def _record(self, method: str, path: str, json: dict | None = None, **kwargs):
        full_url = f"{self.api_base}{path}"
        self.calls.append((method, full_url, json))
        return DummyResponse()

    def post(self, path: str, json: dict | None = None, **kwargs):
        return self._record("POST", path, json, **kwargs)

    def put(self, path: str, json: dict | None = None, **kwargs):
        return self._record("PUT", path, json, **kwargs)

    def get(self, path: str, **kwargs):
        return self._record("GET", path, None, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._record("DELETE", path, None, **kwargs)


@pytest.fixture
def dummy_canvas():
    """Fixture version for convenience in tests."""
    return DummyCanvas()
