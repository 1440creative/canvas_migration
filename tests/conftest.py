# tests/conftest.py
import requests

class DummyCanvas:
    """
    Minimal Canvas-like wrapper that matches the CanvasAPI surface.
    Uses a real requests.Session so requests_mock can intercept.
    """
    def __init__(self, api_base: str = "https://api.example.edu"):
        self.api_base = api_base
        self.session = requests.Session()

    def get(self, path: str, **kwargs):
        return self.session.get(f"{self.api_base}/api/v1{path}", **kwargs)

    def post(self, path: str, **kwargs):
        return self.session.post(f"{self.api_base}/api/v1{path}", **kwargs)

    def put(self, path: str, **kwargs):
        return self.session.put(f"{self.api_base}/api/v1{path}", **kwargs)

    def delete(self, path: str, **kwargs):
        return self.session.delete(f"{self.api_base}/api/v1{path}", **kwargs)
