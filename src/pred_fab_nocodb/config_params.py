"""Config-params table client — the single-SSOT config catalog.

One row per config definition, keyed by ``code``. ``value`` is the **runtime SSOT**:
the :meth:`ConfigParamsClient.upsert` is **value-preserving** — re-seeding from the repo
refreshes the *structure* (type/scope/description/options) but never clobbers a
runtime-edited value. ``type`` is the coercion authority for the (text-stored) value;
:func:`coerce_value` is the one place raw → typed happens, so every consumer (rtde's
synthesiser, pred-fab) coerces identically. See the KB note *Cockpit hosting + NocoDB —
implementation plan* (Workstream B).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ._base import _BaseTableClient
from .errors import NotFoundError, ValidationError
from .schema import ConfigParamColumns


class ConfigType(str, Enum):
    """The declared type of a config value — the coercion authority for the text-stored value."""

    REAL = "real"
    INT = "int"
    BOOL = "bool"
    CATEGORICAL = "categorical"
    LIST = "list"


_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def coerce_value(raw: Any, value_type: ConfigType) -> Any:
    """Coerce a raw (text) catalog value to its declared :class:`ConfigType`.

    The single raw→typed authority for config values. Strict: a malformed value for its
    declared type raises rather than silently degrading (matches the audit's anti-heuristic
    stance — the catalog declares the type, so coercion is principled, not guessed).
    """
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
    if value_type is ConfigType.LIST:
        if isinstance(raw, list):
            return raw
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValidationError(f"config value {raw!r} is not a JSON list")
        return parsed
    return str(raw)  # CATEGORICAL


@dataclass(frozen=True)
class ConfigParam:
    """One row from the `config_params` catalog."""

    id: int
    code: str
    value: str
    type: ConfigType
    scope: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    options: list[str] = field(default_factory=list)
    min: Optional[str] = None
    max: Optional[str] = None

    @property
    def coerced(self) -> Any:
        """The value coerced to its declared :class:`ConfigType`."""
        return coerce_value(self.value, self.type)


class ConfigParamsClient(_BaseTableClient):
    """Read/write the `config_params` catalog (link-free; value-preserving upsert)."""

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
        scope: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        options: Optional[list[str]] = None,
        min: Any = None,
        max: Any = None,
    ) -> ConfigParam:
        """Create or update a config row, keyed by ``code``.

        **Value-preserving:** on a row that already exists, refresh the structural metadata
        (``type``/``scope``/``category``/``description``/``options``/``min``/``max``) but
        **never overwrite the stored ``value``** — NocoDB is the runtime SSOT for values, the
        repo seed only for structure. ``value`` is written only on first creation (the seed
        default).
        """
        structure: dict[str, Any] = {
            ConfigParamColumns.CODE: code,
            ConfigParamColumns.TYPE: ConfigType(value_type).value,
            ConfigParamColumns.SCOPE: scope,
            ConfigParamColumns.CATEGORY: category,
            ConfigParamColumns.DESCRIPTION: description,
            ConfigParamColumns.OPTIONS: json.dumps(list(options)) if options is not None else None,
            ConfigParamColumns.MIN: None if min is None else _to_text(min),
            ConfigParamColumns.MAX: None if max is None else _to_text(max),
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
        return self.get_by_code(code)


def _to_text(value: Any) -> str:
    """Serialize a seed default to the text column (catalog stores values as text)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


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
        scope=row.get(ConfigParamColumns.SCOPE) or None,
        category=row.get(ConfigParamColumns.CATEGORY) or None,
        description=row.get(ConfigParamColumns.DESCRIPTION) or None,
        options=[str(o) for o in options],
        min=row.get(ConfigParamColumns.MIN) or None,
        max=row.get(ConfigParamColumns.MAX) or None,
    )
