# tests/conftest.py
import pytest

@pytest.fixture
def tmp_output(tmp_path):
    """Temporary output directory for export tests."""
    return tmp_path
