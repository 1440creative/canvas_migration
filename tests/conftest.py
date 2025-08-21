import requests


class DummyCanvas:
    """
    Minimal Canvas-like wrapper that matches utils/api.CanvasAPI surface.
    It calls requests.request directly so requests_mock can intercept.
    """

    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")

    def _record(self, method: str, path: str, json=None, **kwargs):
        full_url = f"{self.api_base}{path}"
        # 🔑 call requests directly, so requests_mock hooks in
        resp = requests.request(method, full_url, json=json, **kwargs)
        return resp  # <-- return the real Response, not a dummy

    def post(self, path: str, json=None, **kwargs):
        return self._record("POST", path, json=json, **kwargs)

    def put(self, path: str, json=None, **kwargs):
        return self._record("PUT", path, json=json, **kwargs)

    def get(self, path: str, **kwargs):
        return self._record("GET", path, **kwargs)
