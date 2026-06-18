"""Tests for the schema provisioner (create-if-missing config_params, idempotent).

These exercise the provisioner *logic* against the fake (create-when-absent, no-op /
add-missing when present). The real NocoDB v2 meta-API payloads need live validation —
see provision.py's module docstring.
"""
from pred_fab_nocodb.config_params import ConfigCategory, ConfigScope, ConfigType
from pred_fab_nocodb.provision import _config_params_columns, ensure_config_params
from pred_fab_nocodb.schema import ConfigParamColumns, Tables

_EXPECTED_COLS = {c["title"] for c in _config_params_columns()}


def _col(fake_http, title):
    return next(c for c in fake_http.meta_get_table(Tables.CONFIG_PARAMS)["columns"]
                if c["title"] == title)


def test_creates_table_when_absent(fake_http):
    result = ensure_config_params(fake_http, base_id="b1")
    assert result["created_table"] is True
    # Table now exists with the full column set.
    cols = {c["title"] for c in fake_http.meta_get_table(Tables.CONFIG_PARAMS)["columns"]}
    assert cols == _EXPECTED_COLS
    # type / scope / category are SingleSelects over their enums.
    for title, enum in [(ConfigParamColumns.TYPE, ConfigType),
                        (ConfigParamColumns.SCOPE, ConfigScope),
                        (ConfigParamColumns.CATEGORY, ConfigCategory)]:
        col = _col(fake_http, title)
        assert col["uidt"] == "SingleSelect"
        assert {o["title"] for o in col["colOptions"]["options"]} == {m.value for m in enum}
    # min / max stay raw text (coerced per type by the consumer).
    assert _col(fake_http, ConfigParamColumns.MIN)["uidt"] == "SingleLineText"


def test_idempotent_when_present(fake_http):
    ensure_config_params(fake_http, base_id="b1")
    create_calls = [c for c in fake_http.calls if c[0] == "meta_create_table"]
    result = ensure_config_params(fake_http, base_id="b1")   # second run
    assert result["created_table"] is False and result["added_columns"] == []
    # No second table creation.
    assert len([c for c in fake_http.calls if c[0] == "meta_create_table"]) == len(create_calls)


def test_adds_only_missing_columns(fake_http):
    # Pre-existing table with a partial column set.
    fake_http.set_records(Tables.CONFIG_PARAMS, [])
    fake_http.set_columns(Tables.CONFIG_PARAMS, [
        {"title": ConfigParamColumns.CODE, "uidt": "SingleLineText"},
        {"title": ConfigParamColumns.VALUE, "uidt": "LongText"},
    ])
    result = ensure_config_params(fake_http, base_id="b1")
    assert result["created_table"] is False
    assert set(result["added_columns"]) == _EXPECTED_COLS - {ConfigParamColumns.CODE, ConfigParamColumns.VALUE}
