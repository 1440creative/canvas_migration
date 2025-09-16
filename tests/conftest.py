# tests/conftest.py
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# --- Ensure repo root is importable (so tests can import your packages without PYTHONPATH) ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- Minimal in-memory Response stub (no real HTTP) ---
class DummyResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[Dict[str, Any]] = None, text: str = "ok"):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text

    def json(self) -> Dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        # Mirror requests.Response.raise_for_status() behavior
        if 400 <= self.status_code:
            import requests  # only to raise matching error type when needed
            raise requests.HTTPError(f"{self.status_code} Error", response=self)  # type: ignore[misc]


# --- Pure in-memory Canvas client used by tests ---
class DummyCanvas:
    """
    Minimal, network-free Canvas client for tests.

    - Records every call in self.calls as dicts: {"method": "...", "endpoint": "...", ...kwargs}
    - Returns DummyResponse(200, {"ok": True}) by default so importers don't crash
    - Exposes api_base and api_root for compatibility with production code
    - Provides helpers used by file import tests (begin_course_file_upload, _multipart_post)
    """

    def __init__(self, api_base: str = "https://canvas.example"):
        base = api_base.rstrip("/")
        self.api_base: str = base
        self.api_root: str = base
        self.calls: List[Dict[str, Any]] = []

        # Optional per-endpoint stubs if a test wants specific payloads
        # key = (METHOD, endpoint_substring)  ->  value = DummyResponse or callable(**kwargs) -> DummyResponse
        self._stubs: Dict[tuple[str, str], Any] = {}

    # --- Stubbing convenience (optional for tests) ---
    def stub(self, method: str, endpoint_contains: str, response: Any) -> None:
        """
        Register a stubbed response. `response` can be:
          - DummyResponse instance (returned as-is), or
          - callable(**kwargs) -> DummyResponse (built at call time)
        Matching is done via substring on the requested endpoint.
        """
        self._stubs[(method.upper(), endpoint_contains)] = response

    def _match_stub(self, method: str, endpoint: str, **kwargs) -> Optional[DummyResponse]:
        for (m, frag), resp in self._stubs.items():
            if m == method.upper() and frag in endpoint:
                if callable(resp):
                    return resp(**kwargs)
                return resp
        return None

    # --- Internal recorder ---
    def _record(self, method: str, endpoint: str, **kwargs) -> DummyResponse:
        self.calls.append({"method": method.upper(), "endpoint": endpoint, **kwargs})

        # Allow tests to inject specific payloads per endpoint
        stubbed = self._match_stub(method, endpoint, **kwargs)
        if stubbed is not None:
            return stubbed

        # Generic OK response
        return DummyResponse(200, json_data={"ok": True})

    # --- Public HTTP-like methods used by importers ---
    def get(self, endpoint: str, **kwargs) -> DummyResponse:
        return self._record("GET", self._normalize_endpoint(endpoint), **kwargs)

    def post(self, endpoint: str, **kwargs) -> DummyResponse:
        return self._record("POST", self._normalize_endpoint(endpoint), **kwargs)

    def put(self, endpoint: str, **kwargs) -> DummyResponse:
        return self._record("PUT", self._normalize_endpoint(endpoint), **kwargs)

    def delete(self, endpoint: str, **kwargs) -> DummyResponse:
        return self._record("DELETE", self._normalize_endpoint(endpoint), **kwargs)

    # --- Helpers mirrored from real client semantics (without network) ---
    def begin_course_file_upload(
        self,
        course_id: int,
        *,
        name: str,
        parent_folder_path: str,
        on_duplicate: str = "overwrite",
    ) -> Dict[str, Any]:
        """
        Simulate Canvas' "initiate file upload" response shape enough for importer logic.
        Tests can override via `stub("POST", "/courses/{id}/files", DummyResponse(...))` if needed.
        """
        endpoint = f"/api/v1/courses/{course_id}/files"
        payload = {
            "name": name,
            "parent_folder_path": parent_folder_path,
            "on_duplicate": on_duplicate,
        }
        # record the call so tests can assert on it
        self._record("POST", endpoint, json=payload)
        # minimal shape typically expected by importers
        return {
            "upload_url": "https://uploads.example.com/fake-s3",
            "upload_params": {
                "key": f"{parent_folder_path.rstrip('/')}/{name}",
                "Content-Type": "application/octet-stream",
                "on_duplicate": on_duplicate,
            },
        }

    def _multipart_post(self, url: str, *, data: Dict[str, Any], files: Dict[str, Any]) -> DummyResponse:
        """
        Simulate the S3 (or Canvas) multipart POST; just record and return 201 with a plausible JSON.
        """
        # Record as a normal POST call so tests can inspect
        return self._record("POST", url, data=data, files=list(files.keys()))

    # --- Endpoint normalizer (keeps relative/absolute safe) ---
    def _normalize_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return self.api_base
        ep = str(endpoint).strip()

        # Absolute? return as-is (we still treat it as an identifier; no network happens)
        if ep.startswith("http://") or ep.startswith("https://"):
            return ep

        # Normalize to "/api/v1/..." prefix when obvious
        if ep.startswith("/api/v1/"):
            return ep
        if ep.startswith("api/v1/"):
            return "/" + ep
        if ep.startswith("courses/"):
            return "/api/v1/" + ep
        if not ep.startswith("/"):
            return "/" + ep
        return ep


# --- Tiny helper so tests can import the function-under-test cleanly ---
def load_importer(module_path: str, func_name: str):
    """
    Import `func_name` from the module at `module_path`.

    Examples:
      load_importer("importers.import_course_settings", "import_course_settings")
      load_importer("importers.import_files", "import_files")
    """
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)
