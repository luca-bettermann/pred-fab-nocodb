"""Tests for NocoDBClient constructor argument validation."""
import pytest

from pred_fab_nocodb import NocoDBClient
from pred_fab_nocodb.errors import ValidationError


def test_empty_base_url_raises():
    with pytest.raises(ValidationError, match="base_url"):
        NocoDBClient(base_url="", api_token="t", base_id="b")


def test_empty_api_token_raises():
    with pytest.raises(ValidationError, match="api_token"):
        NocoDBClient(base_url="http://x", api_token="", base_id="b")


def test_empty_base_id_raises():
    with pytest.raises(ValidationError, match="base_id"):
        NocoDBClient(base_url="http://x", api_token="t", base_id="")


def test_whitespace_only_value_raises():
    with pytest.raises(ValidationError, match="base_url"):
        NocoDBClient(base_url="   ", api_token="t", base_id="b")


def test_multiple_missing_listed_in_one_error():
    with pytest.raises(ValidationError) as excinfo:
        NocoDBClient(base_url="", api_token="", base_id="")
    msg = str(excinfo.value)
    assert "base_url" in msg
    assert "api_token" in msg
    assert "base_id" in msg
