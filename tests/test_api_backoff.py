# tests/test_api_backoff.py
import logging
import requests
import pytest

from utils.api import CanvasAPI

@pytest.fixture(autouse=True)
def _no_sleep_and_no_jitter(monkeypatch):
    # Make retries instant & deterministic
    monkeypatch.setattr("utils.api.time.sleep", lambda *_: None)
    monkeypatch.setattr("utils.api.random.uniform", lambda *_: 0.0)

def test_retry_on_429_logs_and_succeeds(requests_mock, caplog):
    base = "https://canvas.test/api/v1"
    api = CanvasAPI(base, "tkn")
    url = f"{base}/foo"

    # First call: 429 with Retry-After; second: 200 OK
    requests_mock.get(url, [
        {"status_code": 429, "headers": {"Retry-After": "0.01"}},
        {"status_code": 200, "json": {"ok": True}},
    ])

    with caplog.at_level(logging.WARNING, logger="utils.api"):
        result = api.get("/foo")

    assert result == {"ok": True}
    # We should see a rate-limit warning
    assert any("Rate limited" in rec.message for rec in caplog.records)
    # Two requests were made (retry once)
    assert len(requests_mock.request_history) == 2

def test_retry_on_500_logs_and_succeeds(requests_mock, caplog):
    base = "https://canvas.test/api/v1"
    api = CanvasAPI(base, "tkn")
    url = f"{base}/bar"

    # First call: 500; second: 200 OK
    requests_mock.get(url, [
        {"status_code": 500, "json": {"error": "boom"}},
        {"status_code": 200, "json": {"ok": True}},
    ])

    with caplog.at_level(logging.WARNING, logger="utils.api"):
        result = api.get("/bar")

    assert result == {"ok": True}
    # We should see a server-error warning
    assert any("Server error" in rec.message for rec in caplog.records)
    assert len(requests_mock.request_history) == 2
