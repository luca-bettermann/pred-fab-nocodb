"""`params` config-catalog client — the relational config SSOT (tunable-leaf definitions).

One row per config *definition*, keyed by ``code`` (distinct from `set_exp_params`, which
holds per-experiment param *values*). ``value`` is the runtime SSOT seed default:
:meth:`ConfigParamsClient.upsert` is **value-preserving** — re-seeding from the repo
refreshes the *structure* (label/type/scope/options/bounds/unit/service) but never clobbers
a runtime-edited value. ``type`` is the coercion authority for the (text-stored) value;
:func:`coerce_value` is the one place raw → typed happens, so every consumer (rtde's
synthesiser, pred-fab) coerces identically. See the KB note *Design NocoDB params +
experiment registry*.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from ._rows import _resolve_link_display, _resolve_link_id
from .errors import NotFoundError, ValidationError
from .schema import ConfigParamColumns, ConfigScope, ConfigType, ServiceColumns

__all__ = ["ConfigType", "ConfigScope", "ConfigParam", "ConfigParamsClient", "coerce_value"]

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

    @property
    def coerced(self) -> Any:
        """The value coerced to its declared :class:`ConfigType`."""
        return coerce_value(self.value, self.type)

    @property
    def coerced_min(self) -> Any:
        """The lower sanity bound coerced to the param's type (``None`` if unset).

        rtde's preflight safety check reads these for the params the collision gate
        computes with; bounds share the param's type (a real's bounds are reals)."""
        return None if self.min is None else coerce_value(self.min, self.type)

    @property
    def coerced_max(self) -> Any:
        """The upper sanity bound coerced to the param's type (``None`` if unset)."""
        return None if self.max is None else coerce_value(self.max, self.type)


class ConfigParamsClient(_BaseTableClient):
    """Read/write the `params` config catalog (value-preserving upsert; nullable service link)."""

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
    ) -> ConfigParam:
        """Create or update a definition row, keyed by ``code``.

        **Value-preserving:** on an existing row, refresh the structural metadata
        (label/type/scope/options/bounds/unit) and re-assert the ``service`` link, but
        **never overwrite the stored ``value``** — NocoDB is the runtime SSOT for values, the
        repo seed only for structure. ``value`` is written only on first creation (the seed
        default). ``min``/``max`` are numeric bounds; ``service_id`` links the configured
        service (resolved by the caller)."""
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

        if existing is None:
            self._http.records_create(
                self._table_id, {**structure, ConfigParamColumns.VALUE: _to_text(value)},
            )
        else:
            # Refresh structure only; the runtime value is preserved.
            self._http.records_update(
                self._table_id, {ConfigParamColumns.ID: existing.id, **structure},
            )
        param = self.get_by_code(code)
        if service_id is not None:
            self._link(ConfigParamColumns.SERVICE, param.id, service_id)
            param = self.get_by_code(code)
        return param


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
        service=_resolve_link_display(row.get(ConfigParamColumns.SERVICE), ServiceColumns.NAME),
    )
