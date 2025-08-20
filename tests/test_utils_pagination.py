#tests/test_utils_pagination.py
from utils.pagination import get_list, get_object, list_modules
from utils.api import CanvasAPI

class DummyAPI(CanvasAPI):
    def __init__(self): pass  # do not call super
    def get(self, endpoint, params=None):
        if "modules" in endpoint:
            return [{"id": 1}, {"id": 2}]
        if "courses/123" in endpoint:
            return {"id": 123, "name": "Demo"}
        return []

def test_get_list_delegates():
    api = DummyAPI()
    data = get_list(api, "/courses/1/modules")
    assert [d["id"] for d in data] == [1, 2]

def test_get_object_delegates():
    api = DummyAPI()
    obj = get_object(api, "/courses/123")
    assert obj["id"] == 123

def test_list_modules_helper():
    api = DummyAPI()
    data = list_modules(api, 1)
    assert len(data) == 2
