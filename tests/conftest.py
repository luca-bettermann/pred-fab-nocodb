"""Shared pytest fixtures."""
import pytest


@pytest.fixture
def fake_http():
    """Stub `_HttpClient` substitute for unit tests.

    TODO: implement once HTTP integration logic is built. For now the pure
    helpers (`_axes`, `_codes`) are tested directly without HTTP.
    """
    pytest.skip("fake_http fixture not implemented yet")
