# tests/test_api_env_instantiation.py
import importlib, os, sys
from types import ModuleType

def _reload_clean():
    # Remove cached module so env changes take effect
    sys.modules.pop("utils.api", None)
    import utils.api as api
    importlib.reload(api)
    return api

def test_source_target_none_when_env_missing(monkeypatch):
    # Clear env
    monkeypatch.setenv("PYTHON_DOTENV_DISABLE", "1")

    monkeypatch.delenv("CANVAS_SOURCE_URL", raising=False)
    monkeypatch.delenv("CANVAS_SOURCE_TOKEN", raising=False)
    monkeypatch.delenv("CANVAS_TARGET_URL", raising=False)
    monkeypatch.delenv("CANVAS_TARGET_TOKEN", raising=False)

    api = _reload_clean()
    assert api.source_api is None
    assert api.target_api is None

def test_source_target_present_when_env_set(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLE", "1")
    
    monkeypatch.setenv("CANVAS_SOURCE_URL", "https://source.example.edu")
    monkeypatch.setenv("CANVAS_SOURCE_TOKEN", "tok-source")
    monkeypatch.setenv("CANVAS_TARGET_URL", "https://target.example.edu")
    monkeypatch.setenv("CANVAS_TARGET_TOKEN", "tok-target")

    api = _reload_clean()
    assert api.source_api is not None
    assert api.target_api is not None
    # sanity: the api_roots end with /api/v1/
    assert api.source_api.api_root.endswith("/api/v1/")
    assert api.target_api.api_root.endswith("/api/v1/")
