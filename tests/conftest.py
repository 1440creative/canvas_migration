# tests/conftest.py
import requests

class DummyCanvas:
    """
    Minimal Canvas-like wrapper compatible with utils/api.CanvasAPI.
    Uses a real requests.Session so requests_mock can intercept calls.
    """

    def __init__(self, api_base: str = "https://api.example.edu"):
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()

    def _full_url(self, path: str) -> str:
        # Ensure /api/v1 prefix is included
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.api_base}/api/v1{path}"

    def post(self, path: str, json: dict | None = None):
        resp = self.session.post(self._full_url(path), json=json)
        try:
            return resp.json()
        except Exception:
            return {}

    def put(self, path: str, json: dict | None = None):
        resp = self.session.put(self._full_url(path), json=json)
        try:
            return resp.json()
        except Exception:
            return {}

    def get(self, path: str, params: dict | None = None):
        resp = self.session.get(self._full_url(path), params=params)
        try:
            return resp.json()
        except Exception:
            return {}
