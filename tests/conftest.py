# tests/conftest.py
import requests

class DummyCanvas:
    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")

    def _normalize_path(self, path: str) -> str:
        # Ensure every call has /api/v1 prefix to match mocks
        if not path.startswith("/api/v1"):
            path = "/api/v1" + path
        return path

    def _record(self, method: str, path: str, **kwargs):
        full_url = self.api_base + self._normalize_path(path)
        resp = requests.request(method, full_url, **kwargs)
        resp.raise_for_status()
        return resp

    def get(self, path: str, **kwargs):
        return self._record("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._record("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._record("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._record("DELETE", path, **kwargs)
