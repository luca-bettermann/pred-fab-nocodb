"""Generic value-table client.

`set_exp_params`, `set_exp_features`, and `set_exp_attributes` share the
same `(experiment, code, dim, value)` shape — one parameterised class
serves all three. The differing FK-code column name (`param` / `feature` /
`attribute`) is passed at construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

from ._base import _BaseTableClient
from ._codes import make_value_code
from .events import ParameterUpdateEvent
from .errors import NotFoundError, ValidationError
from .schema import ParamColumns

if TYPE_CHECKING:
    from .dim_positions import DimPositionsClient


@dataclass(frozen=True)
class ValueRow:
    """One row from a `set_exp_*` table."""

    id: int
    code: str
    experiment_id: int
    fk_code: str  # the param/feature/attribute code this row references
    dim_id: Optional[int]
    axes: dict[str, int]  # resolved from dim_positions; empty when dim is null
    value: Any  # str for params, float for features/attributes


@dataclass(frozen=True)
class ValueWriteItem:
    """Single value to write — used by `write_batch`."""

    value_code: str
    value: Any
    domain: Optional[str] = None
    axes: Optional[Mapping[str, int]] = None


class ValueClient(_BaseTableClient):
    """Generic CRUD for `set_exp_params` / `set_exp_features` / `set_exp_attributes`.

    Parameterised by the target table's id and the FK-code column name
    (`param` / `feature` / `attribute`). Reuses a shared `DimPositionsClient`
    so its in-process cache benefits every write.
    """

    # The shared columns (id/code/experiment/dim/value) live on `ParamColumns`
    # but are identical across all three tables — using `ParamColumns.*` here
    # is a safe shorthand.

    def __init__(
        self,
        http,
        base_id: str,
        table_id: str,
        *,
        fk_code_column: str,
        dim_client: "DimPositionsClient",
        link_field_ids: dict[str, str] | None = None,
        reverse_link_ids: dict[str, tuple[str, str]] | None = None,
    ):
        super().__init__(http, base_id, table_id, link_field_ids=link_field_ids)
        self._fk_col = fk_code_column
        self._dim_client = dim_client
        # `reverse_link_ids[field_name] = (parent_table_id, parent_reverse_field_id)`
        # — when populated, `write_batch` issues ONE parent-side `/links/`
        # call per (parent_id, group_of_children) instead of N child-side
        # calls. Empty in unit-test fixtures that don't seed `colOptions`;
        # the write path falls back to per-row child-side links.
        self._reverse_link_ids: dict[str, tuple[str, str]] = reverse_link_ids or {}

    # ─── Write ────────────────────────────────────────────────────────

    def write(
        self,
        *,
        exp_id: int,
        exp_code: str,
        value_code: str,
        value: Any,
        domain: Optional[str] = None,
        axes: Optional[Mapping[str, int]] = None,
    ) -> ValueRow:
        """Upsert a single value, keyed by the derived row code.

        If a row already exists at the same ``(exp_code, value_code, dim_code)``
        composite, its ``value`` is patched; otherwise a new row is inserted.
        Link fields (``experiment``, ``dim``) are re-asserted via the /links/
        endpoint regardless — NocoDB treats re-linking the same target as a
        no-op.

        If ``axes`` is provided, ``domain`` must also be provided; the
        corresponding ``dim_position`` is upserted via the shared
        ``DimPositionsClient``. If ``axes`` is ``None``, the row's ``dim``
        link stays null (per-experiment scope).
        """
        dim_id, dim_code = self._resolve_dim(domain=domain, axes=axes)
        row_code = make_value_code(exp_code=exp_code, value_code=value_code, dim_code=dim_code)

        existing = self._try_lookup_by_code(row_code)
        if existing is None:
            insert_body = self._build_body(
                row_code=row_code, value_code=value_code, value=value,
            )
            self._http.records_create(self._table_id, insert_body)
            row = self._lookup_by_code(row_code)
        else:
            update_body = {ParamColumns.ID: int(existing[ParamColumns.ID]), ParamColumns.VALUE: value}
            self._http.records_update(self._table_id, update_body)
            row = self._lookup_by_code(row_code)

        record_id = int(row[ParamColumns.ID])
        self._link(ParamColumns.EXPERIMENT, record_id, exp_id)
        if dim_id is not None:
            self._link(ParamColumns.DIM, record_id, dim_id)
        return self._row_to_value(self._lookup_by_code(row_code))

    def write_batch(
        self,
        *,
        exp_id: int,
        exp_code: str,
        items: list[ValueWriteItem],
    ) -> list[ValueRow]:
        """Upsert each row, batching inserts but updating individually.

        Splits items by whether their derived row code already exists:
          - new rows go into a single bulk records-create
          - existing rows get individual records-update PATCHes
        Link fields are re-asserted afterwards via the /links/ endpoint
        (NocoDB v2's records endpoint silently drops link-field values
        regardless of single vs bulk; the /links/ path is the only
        reliable wire).
        """
        if not items:
            return []
        # Resolve dims (cached) and pre-compute the row code for every item.
        per_item_dim_ids: list[Optional[int]] = []
        row_codes: list[str] = []
        for item in items:
            dim_id, dim_code = self._resolve_dim(domain=item.domain, axes=item.axes)
            row_codes.append(
                make_value_code(
                    exp_code=exp_code, value_code=item.value_code, dim_code=dim_code,
                )
            )
            per_item_dim_ids.append(dim_id)

        # Partition into "new" (bulk insert) vs "existing" (per-row update).
        insert_bodies: list[dict[str, Any]] = []
        update_bodies: list[dict[str, Any]] = []
        for item, row_code in zip(items, row_codes):
            existing = self._try_lookup_by_code(row_code)
            if existing is None:
                insert_bodies.append(
                    self._build_body(
                        row_code=row_code,
                        value_code=item.value_code,
                        value=item.value,
                    )
                )
            else:
                update_bodies.append({
                    ParamColumns.ID: int(existing[ParamColumns.ID]),
                    ParamColumns.VALUE: item.value,
                })

        if insert_bodies:
            self._http.records_create(self._table_id, insert_bodies)
        if update_bodies:
            self._http.records_update(self._table_id, update_bodies)

        # Re-fetch every row to get the (now-stable) ids, then assert links.
        # Collect record ids first so we can issue one bulk parent-side
        # `/links/` call per (parent_id, group_of_children) instead of 2N
        # child-side calls (one per row × each LTAR). Falls back to per-row
        # child-side calls when the reverse-link map isn't resolved (unit
        # tests that don't seed `colOptions`).
        record_ids: list[int] = []
        record_ids_by_dim: dict[int, list[int]] = {}
        for row_code, dim_id in zip(row_codes, per_item_dim_ids):
            row = self._lookup_by_code(row_code)
            record_id = int(row[ParamColumns.ID])
            record_ids.append(record_id)
            if dim_id is not None:
                record_ids_by_dim.setdefault(dim_id, []).append(record_id)

        # 1 call linking every child row → exp_id (from the experiment side).
        self._safe_link_batch(ParamColumns.EXPERIMENT, exp_id, record_ids)

        # K calls for dim links — one per unique dim_id, batching its child rows.
        for dim_id, child_ids in record_ids_by_dim.items():
            self._safe_link_batch(ParamColumns.DIM, dim_id, child_ids)

        # Re-fetch each row to capture the now-asserted links in the returned ValueRow.
        return [self._row_to_value(self._lookup_by_code(row_code)) for row_code in row_codes]

    def _safe_link_batch(
        self,
        field_name: str,
        parent_id: int,
        child_record_ids: list[int],
    ) -> None:
        """Link children to parent, tolerating stale IDs after DB rebuilds.

        Tries reverse-batch first, falls back to per-row child-side, and
        swallows NotFoundError on either path — the value rows are already
        written; links can be re-asserted later.
        """
        if not child_record_ids:
            return
        try:
            if self._link_reverse_batch(field_name, parent_id, child_record_ids):
                return
        except NotFoundError:
            pass
        for record_id in child_record_ids:
            try:
                self._link(field_name, record_id, parent_id)
            except NotFoundError:
                pass

    def _link_reverse_batch(
        self,
        field_name: str,
        parent_record_id: int,
        child_record_ids: list[int],
    ) -> bool:
        """Bulk-link from the parent side: ONE call sets all child links.

        Returns True iff the reverse-link metadata for ``field_name`` was
        resolved at construction (and the link call was made). Returns
        False otherwise so the caller can fall back to per-row child-side
        ``_link`` calls — that's the path unit-test fixtures take when
        they don't seed ``colOptions.fk_related_model_id``.
        """
        pair = self._reverse_link_ids.get(field_name)
        if pair is None:
            return False
        parent_table_id, parent_reverse_field_id = pair
        if not child_record_ids:
            return True
        self._http.link_records(
            table_id=parent_table_id,
            link_field_id=parent_reverse_field_id,
            record_id=parent_record_id,
            linked_record_ids=list(child_record_ids),
        )
        return True

    def _try_lookup_by_code(self, row_code: str) -> Optional[dict[str, Any]]:
        """Like `_lookup_by_code` but returns None instead of raising."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({ParamColumns.CODE},eq,{row_code})",
            limit=1,
        )
        return rows[0] if rows else None

    # ─── Read ─────────────────────────────────────────────────────────

    def read(
        self,
        *,
        exp_code: str,
        value_code: Optional[str] = None,
    ) -> list[ValueRow]:
        """Read every row for an experiment, optionally filtered by FK code.

        Filters by ``exp_code`` (the LTAR display value) — NocoDB v2 compares
        LTAR fields against the linked record's primary value, not the id.
        """
        clauses = [f"({ParamColumns.EXPERIMENT},eq,{exp_code})"]
        if value_code is not None:
            clauses.append(f"({self._fk_col},eq,{value_code})")
        rows = self._http.records_list(self._table_id, where="~and".join(clauses))
        return [self._row_to_value(r) for r in rows]

    def read_static(self, exp_code: str) -> dict[str, Any]:
        """Every value where `dim` is unset, returned as `{value_code: value}`.

        Useful for `set_exp_params` to retrieve per-experiment static values
        before a fab run.

        Uses NocoDB v2's ``blank`` operator — ``is,null`` does not work on
        LTAR fields and silently filters every row out.
        """
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({ParamColumns.EXPERIMENT},eq,{exp_code})"
                f"~and({ParamColumns.DIM},blank,)"
            ),
        )
        result: dict[str, Any] = {}
        for r in rows:
            if self._fk_col not in r:
                continue
            raw = r[ParamColumns.VALUE]
            if isinstance(raw, str):
                try:
                    raw = int(raw) if raw.lstrip("-").isdigit() else float(raw)
                except (ValueError, AttributeError):
                    pass
            result[str(r[self._fk_col])] = raw
        return result

    def read_trajectory(
        self,
        exp_code: str,
    ) -> dict[str, list[tuple[dict[str, int], Any]]]:
        """Every value where ``dim`` is populated, grouped by code.

        Returns ``{value_code: [(axes, value), ...]}``. Used for features and
        attributes where multi-axis positions are valid. For params, prefer
        :meth:`read_parameter_updates` which projects to pred-fab's
        canonical single-axis :class:`ParameterUpdateEvent` shape.

        Uses NocoDB v2's ``notblank`` operator (LTAR-aware null check); a
        client-side ``dim_id is None`` skip remains as belt-and-suspenders.
        """
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({ParamColumns.EXPERIMENT},eq,{exp_code})"
                f"~and({ParamColumns.DIM},notblank,)"
            ),
        )
        out: dict[str, list[tuple[dict[str, int], Any]]] = {}
        for r in rows:
            code = str(r.get(self._fk_col, ""))
            if not code:
                continue
            dim_id = self._extract_dim_id(r.get(ParamColumns.DIM))
            if dim_id is None:
                continue
            position = self._dim_client.get(dim_id)
            out.setdefault(code, []).append((dict(position.axes), r[ParamColumns.VALUE]))
        return out

    def read_parameter_updates(self, exp_code: str) -> list[ParameterUpdateEvent]:
        """Every value where ``dim`` is populated, grouped into sparse events.

        Rows sharing the same dim_position collapse into one
        :class:`ParameterUpdateEvent` whose ``updates`` dict bundles every
        ``(value_code, value)`` at that step. Each row's dim_position must
        be single-axis; multi-axis positions raise ``ValidationError`` since
        the canonical ``ParameterUpdateEvent`` carries one ``(iterator_code,
        step_index)`` pair only.

        Use this on the params client; features and attributes (which may
        carry multi-axis positions like ``{layer_idx, node_idx}``) should
        go through :meth:`read_trajectory` instead.

        Returns events sorted by ``(iterator_code, step_index)``. The shape is
        the same one pred-fab uses internally
        (``ExperimentData.parameter_updates``), so the two layers exchange
        events directly without translation.
        """
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({ParamColumns.EXPERIMENT},eq,{exp_code})"
                f"~and({ParamColumns.DIM},notblank,)"
            ),
        )
        by_dim: dict[int, dict[str, Any]] = {}
        for r in rows:
            code = str(r.get(self._fk_col, ""))
            if not code:
                continue
            dim_id = self._extract_dim_id(r.get(ParamColumns.DIM))
            if dim_id is None:
                continue
            raw = r[ParamColumns.VALUE]
            if isinstance(raw, str):
                try:
                    raw = int(raw) if raw.lstrip("-").isdigit() else float(raw)
                except (ValueError, AttributeError):
                    pass
            by_dim.setdefault(dim_id, {})[code] = raw

        events: list[ParameterUpdateEvent] = []
        for dim_id, updates in by_dim.items():
            position = self._dim_client.get(dim_id)
            if len(position.axes) != 1:
                raise ValidationError(
                    f"dim_position {position.code!r} is multi-axis "
                    f"({position.axes!r}); cannot project onto a single-axis "
                    "ParameterUpdateEvent."
                )
            dim, step = next(iter(position.axes.items()))
            events.append(
                ParameterUpdateEvent(
                    updates=dict(updates),
                    iterator_code=dim,
                    step_index=int(step),
                )
            )
        events.sort(key=lambda e: (e.iterator_code or "", e.step_index or 0))
        return events

    # ─── Internal ──────────────────────────────────────────────────────

    def _resolve_dim(
        self,
        *,
        domain: Optional[str],
        axes: Optional[Mapping[str, int]],
    ) -> tuple[Optional[int], Optional[str]]:
        """Resolve (domain, axes) to (dim_id, dim_code). Both None for static scope."""
        if axes is None:
            return None, None
        if domain is None:
            raise ValueError("`domain` is required when `axes` is provided")
        position = self._dim_client.get_or_create(domain=domain, axes=axes)
        return position.id, position.code

    def _build_body(
        self,
        *,
        row_code: str,
        value_code: str,
        value: Any,
    ) -> dict[str, Any]:
        """Build a records-create body with non-LTAR columns only.

        ``experiment`` and ``dim`` are LTAR fields and are wired post-create
        via the /links/ endpoint, not via inline POST values.
        """
        return {
            ParamColumns.CODE: row_code,
            self._fk_col: value_code,
            ParamColumns.VALUE: value,
        }

    def _lookup_by_code(self, row_code: str) -> dict[str, Any]:
        rows = self._http.records_list(
            self._table_id,
            where=f"({ParamColumns.CODE},eq,{row_code})",
            limit=1,
        )
        if not rows:
            raise RuntimeError(f"Value row with code={row_code!r} not found after insert")
        return rows[0]

    def _row_to_value(self, row: dict[str, Any]) -> ValueRow:
        dim_id = self._extract_dim_id(row.get(ParamColumns.DIM))
        axes: dict[str, int] = {}
        if dim_id is not None:
            try:
                pos = self._dim_client.get(dim_id)
                axes = dict(pos.axes)
            except Exception:
                pass
        return ValueRow(
            id=int(row[ParamColumns.ID]),
            code=str(row[ParamColumns.CODE]),
            experiment_id=self._extract_link_id(row.get(ParamColumns.EXPERIMENT)) or 0,
            fk_code=str(row.get(self._fk_col, "")),
            dim_id=dim_id,
            axes=axes,
            value=row.get(ParamColumns.VALUE),
        )

    @staticmethod
    def _extract_link_id(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, list):
            if not value:
                return None
            first = value[0]
            return int(first.get("Id", 0)) if isinstance(first, dict) else int(first)
        if isinstance(value, dict):
            return int(value.get("Id", 0)) or None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_dim_id(value: Any) -> Optional[int]:
        return ValueClient._extract_link_id(value)
