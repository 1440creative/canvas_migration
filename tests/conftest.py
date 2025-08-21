#tests/conftest.py
import json
import pytest
import requests
from pathlib import Path

@pytest.fixture
def tmp_export(tmp_path):
    # export_root/data/<course_id> layout
    root = tmp_path / "export" / "data" / "101"
    (root / "files").mkdir(parents=True)
    return root

@pytest.fixture
def id_map():
    #in-memory id_map used by importers;
    return {}

class DummyCanvas:
    """
    Minimal Canvas-like client for tests.
    - has a requests.Session so requests_mock can intercept
    """
    
    def __init__(self, api_root="https://api.test/api/v1/"):
        self.api_root = api_root
        self.session = requests.Session()
        
    #passthroughs
        
    def post(self, endpoint, **kwargs):
        return self.session.post(self._url(endpoint), **kwargs)
        
    def post_json(self, endpoint, *, payload):
        r = self.post(endpoint, json=payload)
        r.raise_for_status()
        return r.json()
    
    def _url(self, endpoint: str) -> str:
        ep = endpoint.lstrip("/")
        if ep.startswith("api/v1/"):
            ep = ep[len("api/v1/"):]
        return self.api_root + ep
    
    #import_files calls:
    def begin_course_file_upload(self, course_id: int, *, name: str, parent_folder_path: str, on_duplicate="overwrite"):
        #tests stub upload_url using requests_mock
        return {"upload_url": "https://uploads.test/upload", "upload_params": {}}
    
    def _multipart_post(self, url: str, *, data, files):
        #same session; requests_mock intercept
        return self.session.post(url, data=data, files=files)

@pytest.fixture
def dummy_canvas():
    return DummyCanvas()