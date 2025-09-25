# utils/api.py
from __future__ import annotations

import os
import time
import requests
import logging
import random
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from urllib.parse import urljoin

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:  # python-dotenv not installed in some test envs
    _load_dotenv = None

def _load_env_if_opted_in() -> None:
    """
    only load .env files when explicitly opted in
    - Set PYTHON_DOTENV_LOAD=1 to enable
    - PYTHON_DOTENV_DISABLE=1 always disables
    """
    if os.getenv("PYTHON_DOTENV_DISABLE") == "1":
        return
    if os.getenv("PYTHON_DOTENV_LOAD") == "1":
        return
    if _load_dotenv is None:
        return

    # Load env files (repo defaults, then local overrides)
    from dotenv import load_dotenv  # type: ignore
    _load_dotenv(str(REPO_ROOT / ".env"))
    _load_dotenv(str(REPO_ROOT / ".env.local"), override=True)

# Do NOT load by default; tests control the environment.
_load_env_if_opted_in()

# --- Tunables ---------------------------------------------------------------
DEFAULT_TIMEOUT: tuple[float, float] = (5, 30)  # (connect, read) seconds
DEFAULT_PER_PAGE = 100
USER_AGENT = "CanvasMigrations/1.0 (+https://example.org)"  # customize
API_PREFIX = "/api/v1"

# Allow overrides via env (e.g., CANVAS_HTTP_TIMEOUT="10,300")
_to = os.getenv("CANVAS_HTTP_TIMEOUT") or os.getenv("CANVAS_TIMEOUT")
if _to:
    try:
        parts = [float(p.strip()) for p in _to.split(",")]
        if len(parts) == 2:
            DEFAULT_TIMEOUT = (parts[0], parts[1])  # type: ignore[assignment]
    except Exception:
        pass

log = logging.getLogger(__name__)


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
                    jitter = random.uniform(0, 0.25 * retry_after)
                    wait_time = retry_after + jitter
                    log.warning(
                        "Rate limited: 429 received. Retrying after %.2fs (attempt %s/%s)",
                        wait_time, attempt, max_attempts,
                        extra={"url": url, "retry_after": retry_after},
                    )
                    time.sleep(wait_time)
                    continue

                resp.raise_for_status()
                return resp

            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status and status >= 500 and attempt < max_attempts:
                    jitter = random.uniform(0, 0.25 * delay)
                    wait_time = delay + jitter
                    log.warning(
                        "Server error %s. Retrying after %.2fs (attempt %s/%s)",
                        status, wait_time, attempt, max_attempts,
                        extra={"url": url},
                    )
                    time.sleep(wait_time)
                    delay *= 2
                    continue
                raise

            except (requests.ConnectionError, requests.Timeout):
                if attempt < max_attempts:
                    jitter = random.uniform(0, 0.25 * delay)
                    wait_time = delay + jitter
                    log.warning(
                        "Connection/timeout error. Retrying after %.2fs (attempt %s/%s)",
                        wait_time, attempt, max_attempts,
                        extra={"url": url},
                    )
                    time.sleep(wait_time)
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
            # Only send params on the first request; follow-ups use absolute next URLs.
            r = self._request("GET", url, params=params if not results else None)
            data = r.json()

            if isinstance(data, list):
                results.extend(data)
            else:
                return data  # single object; no pagination

            # RFC5988 Link header parsing (rel=next or rel="next")
            url = self._next_link(r.headers)

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
        return self.post_json(f"/api/v1/courses/{course_id}/files", payload=payload)

    def _next_link(self, headers: Dict[str, Any]) -> Optional[str]:
        """
        Extract the 'next' URL from an RFC5988 Link header.
        Accepts rel=next and rel="next". Returns None if not present.
        """
        link_hdr = headers.get("Link") or headers.get("link")
        if not link_hdr:
            return None
        for raw in link_hdr.split(","):
            parts = [p.strip() for p in raw.split(";")]
            if not parts or not (parts[0].startswith("<") and ">" in parts[0]):
                continue
            url_part = parts[0]
            rel_parts = [p.lower() for p in parts[1:]]
            if any(r == "rel=next" or r == 'rel="next"' for r in rel_parts):
                return url_part[url_part.find("<") + 1 : url_part.find(">")]
        return None

    def _multipart_post(self, url: str, *, data: Dict[str, Any], files: Dict[str, Any]) -> requests.Response:
        """
        Perform a multipart/form-data POST (used for Canvas file uploads).
        Retries on 5xx/timeouts; strips default JSON content-type.
        """
        headers = self.session.headers.copy()
        headers.pop("Content-Type", None)  # let requests set multipart boundary

        max_attempts = 4
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.post(url, data=data, files=files, headers=headers, timeout=DEFAULT_TIMEOUT)
                # Treat 5xx as retryable
                if 500 <= resp.status_code < 600:
                    raise requests.HTTPError(f"{resp.status_code} server error", response=resp)
                resp.raise_for_status()
                return resp
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_err = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                if attempt == max_attempts or not (status is None or status >= 500):
                    break
                jitter = random.uniform(0, 0.25 * delay)
                time.sleep(delay + jitter)
                delay *= 2
        if isinstance(last_err, requests.HTTPError) and last_err.response is not None:
            # Bubble up with context
            raise last_err
        raise requests.HTTPError("multipart upload failed")  # generic

    @staticmethod
    def _json_or_empty(resp: requests.Response) -> dict:
        """
        Return parsed JSON if the response looks like JSON; otherwise {}.
        Safely handles 204, empty bodies, and malformed JSON.
        """
        if resp.status_code == 204 or not resp.content:
            return {}
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype.lower():
            try:
                return resp.json()
            except ValueError:
                return {}
        return {}

def _maybe_api(url_env: str, token_env: str) -> Optional["CanvasAPI"]:
    url = os.getenv(url_env)
    token = os.getenv(token_env)
    if url and token:
        try:
            return CanvasAPI(url, token)
        except Exception:
            # Leave uninitialized if constructor validation fails
            return None
    return None

# Note: these may be None if env vars are not set.
source_api: Optional["CanvasAPI"] = _maybe_api("CANVAS_SOURCE_URL", "CANVAS_SOURCE_TOKEN")
target_api: Optional["CanvasAPI"] = _maybe_api("CANVAS_TARGET_URL", "CANVAS_TARGET_TOKEN")

# Optional: make the module’s public surface explicit
__all__ = [
    "CanvasAPI",
    "DEFAULT_TIMEOUT",
    "DEFAULT_PER_PAGE",
    "USER_AGENT",
    "API_PREFIX",
    "source_api",
    "target_api",
]
