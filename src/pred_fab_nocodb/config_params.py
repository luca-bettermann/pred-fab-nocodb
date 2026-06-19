"""`params` config-catalog client — the relational config SSOT (tunable-leaf definitions).

One row per config *definition*, keyed by ``code`` (distinct from `set_exp_params`, which
holds per-experiment param *values*). ``value`` is the seed default; the upsert is
**value-preserving for tunable scopes** (`knob`/`editable` — NocoDB is the runtime SSOT) but
**seed-authoritative for `constant`/`safety`** (config-as-code — re-seed overwrites). ``type``
is the coercion authority for the (text-stored) value; :func:`coerce_value` is the one place
raw → typed happens. A param has a **polymorphic owner** — at most one of service/hardware/unit
(0 = global); >1 fails loud (NocoDB can't enforce the exclusivity). See the KB note *Design
NocoDB params + experiment registry*.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Optional

from ._base import _BaseTableClient
from ._rows import _resolve_link_display, _resolve_link_id
from .errors import NotFoundError, ValidationError
from .schema import (
    ConfigParamColumns,
    ConfigScope,
    ConfigType,
    HardwareColumns,
    SEED_AUTHORITATIVE_SCOPES,
    ServiceColumns,
    UnitColumns,
)

__all__ = ["ConfigType", "ConfigScope", "ConfigParam", "ParamOwner", "ConfigParamsClient", "coerce_value"]

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def coerce_value(raw: Any, value_type: ConfigType) -> Any:
    """Coerce a raw (text) catalog value to its declared :class:`ConfigType`.

    The single raw→typed authority for config values. Strict: a malformed value for its
    declared type raises rather than silently degrading (the catalog declares the type, so
    coercion is principled, not guessed)."""
    if raw is None:
        return None
    if value_type is ConfigType.REAL:
        return float(raw)
    if value_type is ConfigType.INT:
        return int(raw)
    if value_type is ConfigType.BOOL:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ValidationError(f"config value {raw!r} is not a valid bool")
    if value_type in (ConfigType.LIST, ConfigType.VECTOR):
        parsed = raw if isinstance(raw, list) else json.loads(raw)
        if not isinstance(parsed, list):
            raise ValidationError(f"config value {raw!r} is not a JSON list")
        return [float(x) for x in parsed] if value_type is ConfigType.VECTOR else parsed
    return str(raw)  # CATEGORICAL


class ParamOwner(NamedTuple):
    """A param's single owner: ``kind`` (service/hardware/unit), record id, display name."""

    kind: str
    id: int
    name: str


@dataclass(frozen=True)
class ConfigParam:
    """One definition row from the `params` config catalog."""

    id: int
    code: str
    value: str
    type: ConfigType
    label: Optional[str] = None
    scope: Optional[str] = None
    description: Optional[str] = None
    options: list[str] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    unit: Optional[str] = None
    service_id: Optional[int] = None
    service: Optional[str] = None
    hardware_id: Optional[int] = None
    hardware: Optional[str] = None
    unit_owner_id: Optional[int] = None
    unit_owner: Optional[str] = None

    @property
    def coerced(self) -> Any:
        """The value coerced to its declared :class:`ConfigType`."""
        return coerce_value(self.value, self.type)

    @property
    def coerced_min(self) -> Any:
        """The lower sanity bound coerced to the param's type (``None`` if unset)."""
        return None if self.min is None else coerce_value(self.min, self.type)

    @property
    def coerced_max(self) -> Any:
        """The upper sanity bound coerced to the param's type (``None`` if unset)."""
        return None if self.max is None else coerce_value(self.max, self.type)

    @property
    def owner(self) -> Optional[ParamOwner]:
        """The single owner (or ``None`` = global). Raises if 2+ links are set — the
        invariant NocoDB can't enforce, surfaced fail-loud on read as well as write."""
        found = [
            ParamOwner(kind, oid, name or "")
            for kind, oid, name in (
                ("service", self.service_id, self.service),
                ("hardware", self.hardware_id, self.hardware),
                ("unit", self.unit_owner_id, self.unit_owner),
            )
            if oid is not None
        ]
        if len(found) > 1:
            raise ValidationError(
                f"param {self.code!r} has {len(found)} owners ({[o.kind for o in found]}); ≤1 allowed"
            )
        return found[0] if found else None


# Owner-link column → the related table's display field (for read-back resolution).
_OWNER_DISPLAY = {
    ConfigParamColumns.SERVICE: ServiceColumns.NAME,
    ConfigParamColumns.HARDWARE: HardwareColumns.NAME,
    ConfigParamColumns.UNIT_OWNER: UnitColumns.ROLE,
}


class ConfigParamsClient(_BaseTableClient):
    """Read/write the `params` config catalog (scope-aware upsert; ≤1 polymorphic owner)."""

    def get_by_code(self, code: str) -> ConfigParam:
        rows = self._http.records_list(
            self._table_id,
            where=f"({ConfigParamColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"ConfigParam with code={code!r} not found")
        return _row_to_param(rows[0])

    def list_all(self) -> list[ConfigParam]:
        return [_row_to_param(r) for r in self._http.records_list(self._table_id)]

    def read(self) -> dict[str, ConfigParam]:
        """Whole catalog keyed by ``code`` (what a config loader consumes)."""
        return {p.code: p for p in self.list_all()}

    def upsert(
        self,
        *,
        code: str,
        value: Any,
        value_type: ConfigType,
        label: Optional[str] = None,
        scope: Optional[str] = None,
        description: Optional[str] = None,
        options: Optional[list[str]] = None,
        min: Optional[float] = None,
        max: Optional[float] = None,
        unit: Optional[str] = None,
        service_id: Optional[int] = None,
        hardware_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> ConfigParam:
        """Create or update a definition row, keyed by ``code``; set its ≤1 owner link.

        **Scope-aware value authority:** ``value`` is written on creation and, for
        **`constant`/`safety`** scopes, re-written on every upsert (seed-authoritative —
        config-as-code). For **`knob`/`editable`** it is preserved on update (NocoDB is the
        runtime SSOT). The owner is at most one of ``service_id``/``hardware_id``/``unit_id``
        (resolved by the caller) — **2+ raises** (the exclusivity NocoDB can't enforce)."""
        owners = {
            ConfigParamColumns.SERVICE: service_id,
            ConfigParamColumns.HARDWARE: hardware_id,
            ConfigParamColumns.UNIT_OWNER: unit_id,
        }
        set_owners = {col: oid for col, oid in owners.items() if oid is not None}
        if len(set_owners) > 1:
            raise ValidationError(
                f"param {code!r} given {len(set_owners)} owners ({sorted(set_owners)}); ≤1 allowed"
            )

        structure: dict[str, Any] = {
            ConfigParamColumns.CODE: code,
            ConfigParamColumns.LABEL: label,
            ConfigParamColumns.TYPE: ConfigType(value_type).value,
            ConfigParamColumns.SCOPE: ConfigScope(scope).value if scope is not None else None,
            ConfigParamColumns.OPTIONS: json.dumps(list(options)) if options is not None else None,
            ConfigParamColumns.MIN: min,
            ConfigParamColumns.MAX: max,
            ConfigParamColumns.UNIT: unit,
            ConfigParamColumns.DESCRIPTION: description,
        }
        try:
            existing: Optional[ConfigParam] = self.get_by_code(code)
        except NotFoundError:
            existing = None

        seed_authoritative = scope is not None and ConfigScope(scope) in SEED_AUTHORITATIVE_SCOPES
        if existing is None:
            self._http.records_create(
                self._table_id, {**structure, ConfigParamColumns.VALUE: _to_text(value)},
            )
        else:
            body = {ConfigParamColumns.ID: existing.id, **structure}
            if seed_authoritative:
                body[ConfigParamColumns.VALUE] = _to_text(value)  # config-as-code: re-seed wins
            self._http.records_update(self._table_id, body)

        param = self.get_by_code(code)
        for col, oid in set_owners.items():
            self._link(col, param.id, oid)
        return self.get_by_code(code) if set_owners else param


def _to_text(value: Any) -> str:
    """Serialize a seed default to the text value column (the catalog stores values as text)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _to_float(value: Any) -> Optional[float]:
    """Numeric bound from a NocoDB Number cell; ``None`` for blank/unparseable."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_param(row: dict[str, Any]) -> ConfigParam:
    options = row.get(ConfigParamColumns.OPTIONS)
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except (json.JSONDecodeError, TypeError):
            options = []
    if not isinstance(options, list):
        options = []
    return ConfigParam(
        id=int(row[ConfigParamColumns.ID]),
        code=str(row[ConfigParamColumns.CODE]),
        value=str(row.get(ConfigParamColumns.VALUE, "")),
        type=ConfigType(str(row[ConfigParamColumns.TYPE])),
        label=row.get(ConfigParamColumns.LABEL) or None,
        scope=row.get(ConfigParamColumns.SCOPE) or None,
        description=row.get(ConfigParamColumns.DESCRIPTION) or None,
        options=[str(o) for o in options],
        min=_to_float(row.get(ConfigParamColumns.MIN)),
        max=_to_float(row.get(ConfigParamColumns.MAX)),
        unit=row.get(ConfigParamColumns.UNIT) or None,
        service_id=_resolve_link_id(row.get(ConfigParamColumns.SERVICE)),
        service=_resolve_link_display(row.get(ConfigParamColumns.SERVICE), _OWNER_DISPLAY[ConfigParamColumns.SERVICE]),
        hardware_id=_resolve_link_id(row.get(ConfigParamColumns.HARDWARE)),
        hardware=_resolve_link_display(row.get(ConfigParamColumns.HARDWARE), _OWNER_DISPLAY[ConfigParamColumns.HARDWARE]),
        unit_owner_id=_resolve_link_id(row.get(ConfigParamColumns.UNIT_OWNER)),
        unit_owner=_resolve_link_display(row.get(ConfigParamColumns.UNIT_OWNER), _OWNER_DISPLAY[ConfigParamColumns.UNIT_OWNER]),
    )
