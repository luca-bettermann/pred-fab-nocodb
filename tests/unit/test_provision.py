"""Tests for the config-catalog provisioner (create-if-missing, idempotent, LTAR links).

These exercise the provisioner *logic* against the fake (create-when-absent, no-op /
add-missing when present, link creation). The real NocoDB v2 meta-API payloads — especially
the LTAR ``colOptions`` shape — need live validation; see provision.py's module docstring.
"""
from pred_fab_nocodb.provision import _link_specs, provision_config_catalog
from pred_fab_nocodb.schema import (
    ConfigParamColumns,
    ConfigScope,
    ConfigType,
    HardwareColumns,
    HardwareType,
    ServiceColumns,
    Tables,
    UnitColumns,
)

_CATALOG = {Tables.PARAMS, Tables.SERVICES, Tables.USE_CASES, Tables.UNITS, Tables.HARDWARE}


def _cols(fake_http, table):
    return {c["title"]: c for c in fake_http.meta_get_table(table)["columns"]}


def test_creates_all_catalog_tables(fake_http):
    result = provision_config_catalog(fake_http, base_id="b1")
    assert set(result["created_tables"]) == _CATALOG
    pcols = _cols(fake_http, Tables.PARAMS)
    # type / scope are SingleSelects over their enums.
    for title, enum in [(ConfigParamColumns.TYPE, ConfigType), (ConfigParamColumns.SCOPE, ConfigScope)]:
        assert pcols[title]["uidt"] == "SingleSelect"
        assert {o["title"] for o in pcols[title]["colOptions"]["options"]} == {m.value for m in enum}
    # min / max are numeric Number columns (bounds are numeric-only).
    assert pcols[ConfigParamColumns.MIN]["uidt"] == "Number"
    assert pcols[ConfigParamColumns.MAX]["uidt"] == "Number"
    # hardware.type is a SingleSelect over HardwareType.
    htype = _cols(fake_http, Tables.HARDWARE)[HardwareColumns.TYPE]
    assert htype["uidt"] == "SingleSelect"
    assert {o["title"] for o in htype["colOptions"]["options"]} == {m.value for m in HardwareType}


def test_creates_ltar_links(fake_http):
    result = provision_config_catalog(fake_http, base_id="b1")
    assert set(result["added_links"]) == {f"{t}.{c}" for t, c, _, _ in _link_specs()}
    # services.requires is a SELF link back to services.
    req = _cols(fake_http, Tables.SERVICES)[ServiceColumns.REQUIRES]
    assert req["uidt"] == "LinkToAnotherRecord" and req["childId"] == Tables.SERVICES and req["type"] == "mm"
    # the polymorphic owner links on params all target their tables as mm.
    pcols = _cols(fake_http, Tables.PARAMS)
    for col, target in [(ConfigParamColumns.SERVICE, Tables.SERVICES),
                        (ConfigParamColumns.HARDWARE, Tables.HARDWARE),
                        (ConfigParamColumns.UNIT_OWNER, Tables.UNITS)]:
        assert pcols[col]["uidt"] == "LinkToAnotherRecord" and pcols[col]["childId"] == target and pcols[col]["type"] == "mm"
    # units.robot/tool/sensors + services.hardware all link to hardware.
    ucols = _cols(fake_http, Tables.UNITS)
    for col in (UnitColumns.ROBOT, UnitColumns.TOOL, UnitColumns.SENSORS):
        assert ucols[col]["childId"] == Tables.HARDWARE
    assert _cols(fake_http, Tables.SERVICES)[ServiceColumns.HARDWARE]["childId"] == Tables.HARDWARE


def test_idempotent_when_present(fake_http):
    provision_config_catalog(fake_http, base_id="b1")
    creates_before = len([c for c in fake_http.calls if c[0] == "meta_create_table"])
    result = provision_config_catalog(fake_http, base_id="b1")   # second run
    assert result["created_tables"] == [] and result["added_links"] == [] and not result["added_columns"]
    assert len([c for c in fake_http.calls if c[0] == "meta_create_table"]) == creates_before


def test_adds_only_missing_columns(fake_http):
    # Pre-existing params table with a partial column set; the others are absent.
    fake_http.set_records(Tables.PARAMS, [])
    fake_http.set_columns(Tables.PARAMS, [{"title": ConfigParamColumns.CODE, "uidt": "SingleLineText"}])
    result = provision_config_catalog(fake_http, base_id="b1")
    assert Tables.PARAMS not in result["created_tables"]                 # existed already
    added = result["added_columns"][Tables.PARAMS]
    assert ConfigParamColumns.CODE not in added                          # present → not re-added
    assert ConfigParamColumns.LABEL in added                             # missing → added
    assert {Tables.SERVICES, Tables.USE_CASES, Tables.UNITS, Tables.HARDWARE} <= set(result["created_tables"])
