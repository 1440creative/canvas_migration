# utils/api.py
from __future__ import annotations

import os
import time
from typing import Dict, Any, Optional, Union, List
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

# --- Tunables ---------------------------------------------------------------
DEFAULT_TIMEOUT = (5, 30)  # (connect, read) seconds
DEFAULT_PER_PAGE = 100
USER_AGENT = "CanvasMigrations/1.0 (+https://example.org)"  # customize
API_PREFIX = "/api/v1"


class CanvasAPI:
    def __init__(self, base_url: str | None, token: str | None) -> None:
        if not base_url or not token:
            raise ValueError("CanvasAPI base_url and token are required (check your .env)")

        base = base_url.rstrip("/")
        # Ensure exactly one /api/v1 for the API root; keep host root separately if you need it
        if base.endswith(API_PREFIX):
            api_root = base
            host_root = base[: -len(API_PREFIX)]
        else:
            api_root = base + API_PREFIX
            host_root = base

        self.base_url = host_root + "/"   # host root (trailing slash)
        self.api_root = api_root + "/"    # canonical API root (trailing slash)

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })

    # Accept endpoints with or without /api/v1 and build a full API URL
    def _full_url(self, endpoint: str) -> str:
        ep = (endpoint or "").strip()
        if ep.startswith(API_PREFIX):
            ep = ep[len(API_PREFIX):]
        ep = ep.lstrip("/")
        return urljoin(self.api_root, ep)

    # Basic retry/backoff for 429/5xx + timeouts
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        max_attempts = 4
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.request(method, url, timeout=DEFAULT_TIMEOUT, **kwargs)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status and status >= 500 and attempt < max_attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None
            ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        GET with transparent pagination.
        - If the endpoint returns a list, we return a combined list across pages.
        - If it returns a single object, we return that dict.
        """
        url = self._full_url(endpoint)

        params = dict(params or {})
        params.setdefault("per_page", DEFAULT_PER_PAGE)

        results: List[Dict[str, Any]] = []
        while url:
            r = self._request("GET", url, params=params if results == [] else None)
            data = r.json()

            if isinstance(data, list):
                results.extend(data)
            else:
                return data  # single object; no pagination

            # Look for RFC 5988 Link header "rel=next"
            next_url: Optional[str] = None
            link_hdr = r.headers.get("Link") or r.headers.get("link")
            if link_hdr:
                for link in link_hdr.split(","):
                    if 'rel="next"' in link:
                        next_url = link[link.find("<") + 1: link.find(">")]
                        break
            url = next_url

        return results
    
    def post(self, endpoint: str, *, json: Optional[Dict[str, Any]] = None,
             data: Optional[Dict[str, Any]] = None, files=None, params=None) -> requests.Response:
        """
        Raw POST; returns Response. Prefer `json=` when sending JSON bodies because
        the session sets Content-Type: application/json by default.
        """
        url = self._full_url(endpoint)
        return self._request("POST", url, json=json, data=data, files=files, params=params)

    def put(self, endpoint: str, *, json: Optional[Dict[str, Any]] = None,
            data: Optional[Dict[str, Any]] = None, files=None, params=None) -> requests.Response:
        """Raw PUT; returns Response."""
        url = self._full_url(endpoint)
        return self._request("PUT", url, json=json, data=data, files=files, params=params)

    def delete(self, endpoint: str, *, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Raw DELETE; returns Response."""
        url = self._full_url(endpoint)
        return self._request("DELETE", url, params=params)

    def post_json(self, endpoint: str, *, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convenience: POST with JSON body and return parsed JSON.
        """
        r = self.post(endpoint, json=payload)
        return r.json()

    # ---- Canvas-specific helpers ------------------------------------------

    def begin_course_file_upload(
        self,
        course_id: int,
        *,
        name: str,
        parent_folder_path: str,
        on_duplicate: str = "overwrite",  # or "rename"
    ) -> Dict[str, Any]:
        """
        Step 1 of Canvas file upload: returns {"upload_url": ..., "upload_params": {...}, ...}
        Use `requests.post(upload_url, data=upload_params, files={"file": (...)})` for step 2.
        """
        payload = {
            "name": name,
            "parent_folder_path": parent_folder_path,
            "on_duplicate": on_duplicate,
        }
        # Use JSON body to match session default header
        return self.post_json(f"/api/v1/courses/{course_id}/files", payload=payload)
 


# Instantiate two API clients (source/on-prem and target/cloud)
load_dotenv()  # read .env once
source_api = CanvasAPI(
    os.getenv("CANVAS_SOURCE_URL"),
    os.getenv("CANVAS_SOURCE_TOKEN"),
)
target_api = CanvasAPI(
    os.getenv("CANVAS_TARGET_URL"),
    os.getenv("CANVAS_TARGET_TOKEN"),
)
