# tests/conftest.py (replace DummyCanvas with this)
import requests

class DummyCanvas:
    """
    Minimal Canvas-like client for tests.
    - Normalizes endpoints:
        * full URLs (http/https) are used as-is
        * '/api/v1/...' kept as-is (joined to base)
        * 'api/v1/...' gets a leading '/'
        * 'courses/...' is prefixed with '/api/v1/'
        * anything else gets a leading '/'
    - Exposes .session so requests_mock can intercept calls.
    """
    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        # common headers the real client would set
        self.session.headers.update({"Authorization": "Bearer TEST", "Content-Type": "application/json"})

    def _url(self, endpoint: str) -> str:
        if not endpoint:
            return self.api_base
        ep = str(endpoint).strip()

        # Absolute URL? use as-is
        if ep.startswith("http://") or ep.startswith("https://"):
            return ep

        # Normalize common forms
        if ep.startswith("/api/v1/"):
            pass  # already canonical
        elif ep.startswith("api/v1/"):
            ep = "/" + ep
        elif ep.startswith("courses/"):
            ep = "/api/v1/" + ep
        elif not ep.startswith("/"):
            ep = "/" + ep

        return self.api_base + ep

    # Basic HTTP verbs used by importers
    def get(self, endpoint: str, **kwargs) -> requests.Response:
        return self.session.get(self._url(endpoint), **kwargs)

    def post(self, endpoint: str, **kwargs) -> requests.Response:
        return self.session.post(self._url(endpoint), **kwargs)

    def put(self, endpoint: str, **kwargs) -> requests.Response:
        return self.session.put(self._url(endpoint), **kwargs)

    def delete(self, endpoint: str, **kwargs) -> requests.Response:
        return self.session.delete(self._url(endpoint), **kwargs)

    # Convenience used by some importers
    def post_json(self, endpoint: str, *, payload: dict) -> dict:
        resp = self.post(endpoint, json=payload)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {}

    # File-upload helpers (kept for existing file tests)
    def begin_course_file_upload(self, course_id: int, *, name: str, parent_folder_path: str, on_duplicate: str = "overwrite") -> dict:
        # Tests usually mock this POST directly; expose the exact endpoint.
        resp = self.post(f"/api/v1/courses/{course_id}/files", json={
            "name": name,
            "parent_folder_path": parent_folder_path,
            "on_duplicate": on_duplicate,
        })
        resp.raise_for_status()
        return resp.json()

    def _multipart_post(self, url: str, *, data: dict, files: dict) -> requests.Response:
        # Let requests set proper multipart headers
        headers = self.session.headers.copy()
        headers.pop("Content-Type", None)
        resp = self.session.post(url, data=data, files=files, headers=headers)
        return resp
